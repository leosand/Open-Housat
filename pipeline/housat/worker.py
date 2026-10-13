"""Orchestrateur MVP-l4 : backfill d'archive + verification manuelle, frames ancrees t0.
Comparaison vs ancre avec alignement de grille (match_shape), jalons V&V pivot,
pv_sum honnete, bbox de l'image persistee (overlay carte fidele), alertes in-app monotones.
Dedup (site_id, obs_date) AVANT telechargement : une scene deja persistee ne coute rien.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import numpy as np
from shapely.geometry import shape
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from housat import observations as obs
from housat.config import settings
from housat.detection.change import bsi, built_ratio, change_score, ndbi, ndvi
from housat.detection.milestones import Milestone, classify, hold_milestone
from housat.imagery import clouds
from housat.imagery.sentinel2 import SceneMeta, StacContext, fetch_bands, fetch_scl
from housat.imagery.super_resolution import upscale_bands, upscale_rgb_display

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("housat.worker")

MILESTONE_LABELS_FR = {0: "terrain nu", 1: "fondation detectee",
                       2: "structure en progression", 3: "toiture probable",
                       4: "finition / amenagement"}


def _engine() -> Engine:
    return create_engine(settings.database_url)


def _indices(bands: dict[str, np.ndarray]) -> list[np.ndarray]:
    return [ndvi(bands), ndbi(bands), bsi(bands)]


def _bbox4326(polygon: dict) -> list[float]:
    """Emprise de l'image clippee = bbox du polygone (crop rasterio = etendue geometrie)."""
    return [round(v, 6) for v in shape(polygon).bounds]


def _get_site(engine: Engine, site_id: int) -> dict:
    with engine.begin() as c:
        row = c.execute(text("SELECT id, name, owner_email, polygon_geojson FROM sites WHERE id=:i"),
                        {"i": site_id}).mappings().first()
    if row is None:
        raise ValueError(f"chantier {site_id} introuvable")
    return dict(row)


def _load_frame_row(engine: Engine, site_id: int, kind: str) -> dict[str, np.ndarray] | None:
    with engine.begin() as c:
        row = c.execute(text("SELECT data FROM frame_store WHERE site_id=:i AND kind=:k"),
                        {"i": site_id, "k": kind}).first()
    return obs.load_frame(bytes(row[0])) if row else None


def _save_frame(engine: Engine, site_id: int, kind: str, bands: dict[str, np.ndarray]) -> None:
    data = obs.dump_frame(bands)
    with engine.begin() as c:
        c.execute(text("DELETE FROM frame_store WHERE site_id=:i AND kind=:k"), {"i": site_id, "k": kind})
        c.execute(text("INSERT INTO frame_store (site_id, kind, data) VALUES (:i, :k, :d)"),
                  {"i": site_id, "k": kind, "d": data})


def _max_milestone(engine: Engine, site_id: int) -> int:
    with engine.begin() as c:
        row = c.execute(text("SELECT COALESCE(MAX(milestone), -1) FROM observations WHERE site_id=:i"),
                        {"i": site_id}).first()
    return int(row[0])


def _has_observation(engine: Engine, site_id: int, obs_date: str) -> bool:
    """True si une observation existe deja pour (chantier, date d'acquisition)."""
    with engine.begin() as c:
        row = c.execute(text("SELECT 1 FROM observations WHERE site_id=:i AND obs_date=:d"),
                        {"i": site_id, "d": obs_date}).first()
    return row is not None


def _parcel_clear(ctx: StacContext, polygon: dict, scene: SceneMeta) -> tuple[bool, float]:
    """Verdict NUAGE **PAR PARCELLE** (SCL 20 m) — `eo:cloud_cover` couvre toute la tuile (~110 km).

    On lit d'abord le SCL SEUL : si la parcelle est couverte, on evite de telecharger les 5 bandes.
    SCL indisponible -> (True, nan) : repli NON bloquant (mieux vaut tenter la scene que la perdre),
    toujours trace par un WARNING.
    """
    try:
        scl = fetch_scl(ctx, polygon, scene)
    except Exception:  # noqa: BLE001 — panne SCL : ne jamais bloquer la scene pour autant
        logger.warning("SCL indisponible pour %s — scene conservee", scene.acquired, exc_info=True)
        return True, float("nan")
    if scl is None:
        return True, float("nan")
    pct = clouds.parcel_cloud_pct(scl)
    if pct != pct:  # nan : aucune donnee SCL
        return True, pct
    return pct <= settings.max_cloud_cover, pct


def _persist_observation(
    engine: Engine, site_id: int, scene: SceneMeta, bands: dict[str, np.ndarray],
    anchor_idx: list[np.ndarray] | None, sr_method: str, image_bbox: list[float],
    raw_bands: dict[str, np.ndarray] | None = None,
    prev_bands: dict[str, np.ndarray] | None = None,
) -> dict:
    """Calcule indicateurs vs ancre (grille alignee), persiste observation + alerte monotone."""
    base: dict = {"scene_id": scene.item_id, "acquired": scene.acquired.isoformat(),
                  "cloud_cover": scene.cloud_cover, "sr_method": sr_method,
                  "image_bbox": image_bbox}
    if anchor_idx is None:  # premiere scene = ancre, baseline sans comparaison
        payload = {**base, "status": "baseline"}
        milestone, pivot, confidence = Milestone.M0_TERRAIN, False, 0.9
    else:
        bands = obs.match_shape(bands, anchor_idx[0].shape)  # alignement grille (fix V&V)
        pvs, divs = [], []
        for a, curr in zip(anchor_idx, _indices(bands)):
            pv, div = obs.pv_div(a, curr)
            pvs.append(pv)
            divs.append(div)
        # JALON — source unique : le classifieur CONCU `detection/milestones.classify`, alimente
        # par `change_score` (les deux modules sont faits pour s'emboiter : memes noms d'entrees).
        # Avant le 2026-09-19 le worker utilisait un arbre de seuils (`observations.
        # milestone_decision`, supprime) construit sur la seule AMPLEUR du changement : mesure du
        # 2026-09-19 sur 40 observations reelles -> M4 inatteignable (0/6000 tirages) et M2 dans
        # 38 cas sur 40. `classify` separe l'ETAT (`built_ratio`, ou en est le bati) de la
        # TENDANCE (`delta_ndbi_mean`, `delta_bsi_mean`) : c'est la seule facon de distinguer une
        # dalle d'une toiture avec ces donnees.
        prev = obs.match_shape(prev_bands, bands["red"].shape) if prev_bands else None
        cr = change_score(prev, bands) if prev is not None else None
        decision = classify(
            built_ratio=built_ratio(bands),
            delta_ndbi_mean=cr.delta_ndbi_mean if cr is not None else 0.0,
            delta_bsi_mean=cr.delta_bsi_mean if cr is not None else 0.0,
            change_score_value=cr.score if cr is not None else 0.0,
            sr_method=sr_method,
        )
        # Non-regression : le jalon retenu ne redescend jamais sous celui deja atteint.
        milestone = hold_milestone(decision.milestone, _max_milestone(engine, site_id))
        # Indice de reference du pivot : NDBI (bati). `dpra` remplace l'ancienne « croissance »,
        # qui valait en realite l'emprise (le 1er argument de milestone_decision etait toujours
        # nul) et se trouvait exposee sous le nom `delta_pra` — un chiffre juste sous un faux nom.
        piv = obs.detect_pivot_pv(divs[1], pvs[1])
        payload = {**base, "status": "ok",
                   "emprise": round(obs.robust_frac_joint(pvs), 4),
                   "built_ratio": round(built_ratio(bands), 4),
                   "delta_ndbi": round(cr.delta_ndbi_mean, 5) if cr is not None else None,
                   "delta_bsi": round(cr.delta_bsi_mean, 5) if cr is not None else None,
                   "croissance": round(float(piv["dpra"]), 5),
                   "milestone_brut": int(decision.milestone),
                   "activite": round(float(np.mean([np.abs(d).mean() for d in divs])), 5),
                   "pv_sum": round(float(sum(obs.masked_sum(p) for p in pvs)), 3)}
        pivot = bool(piv["qualifie"])
        # `confidence` est celle du classifieur pour CETTE date, meme si le garde-fou a retenu un
        # jalon plus haut. `milestone_brut` conserve le candidat, donc l'ecart est AUDITABLE au lieu
        # d'etre invisible — mesure du 2026-09-19 : un « M3 » stocke avec 0,28 de confiance venait
        # d'un candidat M1 ambigu (0,4 x 0,7 de repli SR) clampe vers le haut.
        confidence = decision.confidence
    # Voie AFFICHAGE : surresolution perceptuelle optionnelle, appliquee aux bandes BRUTES (LR 10 m)
    # et non aux bandes de detection deja x4 (sinon double agrandissement x16, geometrie fausse).
    # Sans modele configure, repli sur l'image de detection (comportement historique).
    src = raw_bands if raw_bands is not None else bands
    try:
        display_bands, display_method = upscale_rgb_display(src)
    except Exception:  # noqa: BLE001 — l'affichage ne doit jamais bloquer la persistance V&V
        display_bands, display_method = bands, "error"
    if display_method != "realesrgan":  # pas de modele SR : image de detection (x4) comme avant
        display_bands = bands
    png = obs.image_png_rgb(display_bands)
    prev_max = _max_milestone(engine, site_id)
    payload.update(milestone=milestone, milestone_label=MILESTONE_LABELS_FR[milestone],
                   pivot_confirme=pivot, confidence=confidence, display_sr=display_method)
    try:
        with engine.begin() as c:
            c.execute(
                text("INSERT INTO observations (site_id, obs_date, milestone, pivot_confirme,"
                     " confidence, payload, image_png, created_at)"
                     " VALUES (:s, :d, :m, :p, :cf, :pl, :img, :t)"),
                {"s": site_id, "d": scene.acquired.isoformat(), "m": milestone, "p": pivot,
                 "cf": confidence, "pl": json.dumps(payload), "img": png,
                 "t": datetime.now(timezone.utc)})
            if milestone > prev_max and milestone > 0:  # alertes monotones ; M0 (terrain nu) = baseline, jamais alerte
                msg = f"Etape franchie : {MILESTONE_LABELS_FR[milestone]}"
                c.execute(text("INSERT INTO alerts (site_id, channel, message, milestone, sent_at)"
                               " VALUES (:s, 'in-app', :m, :ms, :t)"),
                          {"s": site_id, "m": msg, "ms": milestone, "t": datetime.now(timezone.utc)})
                logger.info("site %s : %s", site_id, msg)
    except IntegrityError:
        # course concurrente : un autre worker/API a insere la meme (site_id, obs_date)
        # entre le pre-controle et l'INSERT -> traite comme un doublon, pas une panne.
        logger.info("site %s : conflit concurrent sur %s, traite comme doublon",
                    site_id, scene.acquired.isoformat())
        return {"status": "duplicate", "obs_date": scene.acquired.isoformat()}
    return payload


def backfill_site(engine: Engine | None, site_id: int, *, limit: int = 10) -> dict:
    """Backfill d'archive : scenes les moins nuageuses, ancre t0, jalons par scene.
    Dedup amont : une scene deja en base n'est ni telechargee ni re-super-resolue."""
    engine = engine or _engine()
    site = _get_site(engine, site_id)
    with engine.begin() as c:
        c.execute(text("UPDATE sites SET backfill_status='running', backfill_error=NULL WHERE id=:i"),
                  {"i": site_id})
    try:
        polygon = json.loads(site["polygon_geojson"])
        bbox = _bbox4326(polygon)
        ctx = StacContext()
        scenes = ctx.search_scenes(polygon, limit=limit, mode="archive")
        if not scenes:
            raise RuntimeError("aucune scene sous le seuil de nuages dans la fenetre")
        results, anchor_idx, skipped, cloudy = [], None, 0, 0
        for scene in scenes:
            if _has_observation(engine, site_id, scene.acquired.isoformat()):
                logger.info("site %s : scene %s deja presente, telechargement evite",
                            site_id, scene.acquired)
                skipped += 1
                results.append({"status": "duplicate", "obs_date": scene.acquired.isoformat()})
                continue
            clear, pct = _parcel_clear(ctx, polygon, scene)
            if not clear:
                logger.info("site %s : scene %s ecartee (nuages PARCELLE %.1f %% > %.0f %%)",
                            site_id, scene.acquired, pct, settings.max_cloud_cover)
                cloudy += 1
                results.append({"status": "cloudy", "obs_date": scene.acquired.isoformat(),
                                "parcel_cloud_pct": round(pct, 1)})
                continue
            raw = fetch_bands(ctx, polygon, scene)          # LR 10 m (sert la voie affichage)
            bands, sr_method = upscale_bands(raw)           # voie detection (radiometrique, x4)
            # `prev` est RELU avant d'etre ecrase. La frame etait ecrite depuis le debut et jamais
            # relue (mesure du 2026-09-19 : 0 appel a `_load_frame_row(..., "prev")`), donc
            # `change_score(prev, curr)` — et la tendance du bati qu'il fournit — ne pouvait pas
            # exister. Comme `_save_frame` ecrase « prev » par la scene COURANTE, la lecture doit
            # avoir lieu AVANT l'ecriture.
            prev_bands = _load_frame_row(engine, site_id, "prev") if anchor_idx is not None else None
            if anchor_idx is None:
                anchor_idx = _indices(bands)
                _save_frame(engine, site_id, "anchor", bands)
            _save_frame(engine, site_id, "prev", bands)
            results.append(_persist_observation(engine, site_id, scene, bands, anchor_idx,
                                                sr_method, bbox, raw, prev_bands=prev_bands))
        with engine.begin() as c:
            c.execute(text("UPDATE sites SET backfill_status='done' WHERE id=:i"), {"i": site_id})
        persisted = [r for r in results if r.get("status") != "duplicate"]
        return {"site_id": site_id, "status": "done" if len(scenes) >= 2 else "baseline_only",
                "scenes": len(persisted), "skipped": skipped, "cloudy": cloudy,
                "results": results}
    except Exception as exc:  # noqa: BLE001 — trace en base, jamais silencieux
        logger.exception("backfill site %s", site_id)
        with engine.begin() as c:
            c.execute(text("UPDATE sites SET backfill_status='error', backfill_error=:e WHERE id=:i"),
                      {"e": str(exc)[:500], "i": site_id})
        raise


def check_site(engine: Engine | None, site_id: int) -> dict:
    """Verification manuelle : scene la PLUS RECENTE vs ancre t0 (ou baseline si 1re fois).
    Dedup amont : une scene deja traitee n'est ni telechargee ni re-super-resolue —
    la verification renvoie alors {'status': 'duplicate'} sans cout reseau."""
    engine = engine or _engine()
    site = _get_site(engine, site_id)
    polygon = json.loads(site["polygon_geojson"])
    ctx = StacContext()
    candidates = ctx.search_scenes(polygon, limit=6, window_days=settings.search_window_days,
                                   mode="latest")
    if not candidates:
        return {"site_id": site_id, "status": "cloud_pending"}
    fresh = [s for s in candidates
             if not _has_observation(engine, site_id, s.acquired.isoformat())]
    if not fresh:  # tout est deja analyse : aucun cout reseau
        logger.info("site %s : dernieres scenes deja traitees, aucun telechargement", site_id)
        return {"site_id": site_id, "status": "duplicate",
                "obs_date": candidates[0].acquired.isoformat()}
    # Nuage PAR PARCELLE (SCL) : on retient la plus RECENTE dont la parcelle est degagee —
    # le pre-filtre tuile (large) ne suffit pas a decider.
    scene, pct = None, float("nan")
    for cand in fresh:
        clear, pct = _parcel_clear(ctx, polygon, cand)
        if clear:
            scene = cand
            break
        logger.info("site %s : scene %s ecartee (nuages parcelle %.1f %%)",
                    site_id, cand.acquired, pct)
    if scene is None:
        return {"site_id": site_id, "status": "cloud_pending",
                "parcel_cloud_pct": round(pct, 1) if pct == pct else None}
    raw = fetch_bands(ctx, polygon, scene)           # LR 10 m (voie affichage)
    bands, sr_method = upscale_bands(raw)            # voie detection (x4)
    anchor = _load_frame_row(engine, site_id, "anchor")
    if anchor is None:
        _save_frame(engine, site_id, "anchor", bands)
        anchor_idx = None
    else:
        anchor_idx = _indices(anchor)
    prev_bands = _load_frame_row(engine, site_id, "prev") if anchor_idx is not None else None
    _save_frame(engine, site_id, "prev", bands)
    result = _persist_observation(engine, site_id, scene, bands, anchor_idx,
                                  sr_method, _bbox4326(polygon), raw, prev_bands=prev_bands)
    if pct == pct:
        result["parcel_cloud_pct"] = round(pct, 1)
    return {"site_id": site_id, **result}


def run_once(engine: Engine | None = None) -> None:
    """Mode cron : check les chantiers avec ancre, backfill court (3 scenes) sinon."""
    engine = engine or _engine()
    with engine.begin() as c:
        ids = [r[0] for r in c.execute(text("SELECT id FROM sites WHERE status='active'"))]
    for sid in ids:
        try:
            if _load_frame_row(engine, sid, "anchor"):
                check_site(engine, sid)
            else:
                backfill_site(engine, sid, limit=3)
        except Exception:  # noqa: BLE001
            logger.exception("echec site %s", sid)


def main() -> None:
    p = argparse.ArgumentParser(description="Housat worker")
    p.add_argument("--once", action="store_true")
    p.add_argument("--backfill", type=int, metavar="SITE_ID")
    p.add_argument("--check", type=int, metavar="SITE_ID")
    args = p.parse_args()
    if args.backfill:
        backfill_site(None, args.backfill)
    elif args.check:
        check_site(None, args.check)
    elif args.once:
        run_once()
    else:
        p.error("specifier --once, --backfill SITE_ID ou --check SITE_ID")


if __name__ == "__main__":
    main()
