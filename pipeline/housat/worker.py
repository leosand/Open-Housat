"""Orchestrateur MVP-l2 : backfill d'archive + verification manuelle, frames ancrees t0.
Comparaison vs ancre avec alignement de grille (match_shape), jalons V&V pivot,
pv_sum honnete dans le payload (progression calculable entre periodes arbitraires),
alertes in-app monotones. Pas de canal externe en MVP.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from housat.config import settings
from housat.detection.change import bsi, ndbi, ndvi
from housat.imagery.sentinel2 import SceneMeta, StacContext, fetch_bands
from housat.imagery.super_resolution import upscale_bands
from housat import observations as obs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("housat.worker")

MILESTONE_LABELS_FR = {0: "terrain nu", 1: "fondation detectee",
                       2: "structure en progression", 3: "toiture probable",
                       4: "finition / amenagement"}


def _engine() -> Engine:
    return create_engine(settings.database_url)


def _indices(bands: dict[str, np.ndarray]) -> list[np.ndarray]:
    return [ndvi(bands), ndbi(bands), bsi(bands)]


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


def _persist_observation(
    engine: Engine, site_id: int, scene: SceneMeta, bands: dict[str, np.ndarray],
    anchor_idx: list[np.ndarray] | None, sr_method: str,
) -> dict:
    """Calcule indicateurs vs ancre (grille alignee), persiste observation + alerte monotone."""
    if anchor_idx is None:  # premiere scene = ancre, baseline sans comparaison
        payload: dict = {"scene_id": scene.item_id, "acquired": scene.acquired.isoformat(),
                         "cloud_cover": scene.cloud_cover, "sr_method": sr_method,
                         "status": "baseline"}
        milestone, pivot, confidence = 0, False, 0.9
    else:
        bands = obs.match_shape(bands, anchor_idx[0].shape)  # alignement grille (fix V&V)
        pvs, divs = [], []
        for a, curr in zip(anchor_idx, _indices(bands)):
            pv, div = obs.pv_div(a, curr)
            pvs.append(pv)
            divs.append(div)
        milestone, pivot, growth = obs.milestone_decision(
            [np.zeros_like(p) for p in pvs], pvs, divs)
        emprise = obs.robust_frac_joint(pvs)
        pv_sum = float(sum(obs.masked_sum(p) for p in pvs))
        payload = {"scene_id": scene.item_id, "acquired": scene.acquired.isoformat(),
                   "cloud_cover": scene.cloud_cover, "sr_method": sr_method, "status": "ok",
                   "emprise": round(emprise, 4), "croissance": round(growth, 4),
                   "activite": round(float(np.mean([np.abs(d).mean() for d in divs])), 5),
                   "pv_sum": round(pv_sum, 3)}
        confidence = 0.8 if sr_method == "sen2sr" else 0.55
    png = obs.image_png_rgb(bands)
    prev_max = _max_milestone(engine, site_id)
    payload.update(milestone=milestone, milestone_label=MILESTONE_LABELS_FR[milestone],
                   pivot_confirme=pivot, confidence=confidence)
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO observations (site_id, obs_date, milestone, pivot_confirme, confidence, payload, image_png, created_at)"
                 " VALUES (:s, :d, :m, :p, :cf, :pl, :img, :t)"),
            {"s": site_id, "d": scene.acquired.isoformat(), "m": milestone, "p": pivot,
             "cf": confidence, "pl": json.dumps(payload), "img": png,
             "t": datetime.now(timezone.utc)})
        if milestone > prev_max:  # alertes monotones : jamais de regression signalee
            msg = f"Jalon atteint : {MILESTONE_LABELS_FR[milestone]} (M{milestone})"
            c.execute(text("INSERT INTO alerts (site_id, channel, message, milestone, sent_at)"
                           " VALUES (:s, 'in-app', :m, :ms, :t)"),
                      {"s": site_id, "m": msg, "ms": milestone, "t": datetime.now(timezone.utc)})
            logger.info("site %s : %s", site_id, msg)
    return payload


def backfill_site(engine: Engine | None, site_id: int, *, limit: int = 10) -> dict:
    """Backfill d'archive : scenes les moins nuageuses, ancre t0, jalons par scene."""
    engine = engine or _engine()
    site = _get_site(engine, site_id)
    with engine.begin() as c:
        c.execute(text("UPDATE sites SET backfill_status='running', backfill_error=NULL WHERE id=:i"),
                  {"i": site_id})
    try:
        polygon = json.loads(site["polygon_geojson"])
        ctx = StacContext()
        scenes = ctx.search_scenes(polygon, limit=limit)
        if not scenes:
            raise RuntimeError("aucune scene sous le seuil de nuages dans la fenetre")
        results, anchor_idx = [], None
        for scene in scenes:
            bands, sr_method = upscale_bands(fetch_bands(ctx, polygon, scene))
            if anchor_idx is None:
                anchor_idx = _indices(bands)
                _save_frame(engine, site_id, "anchor", bands)
            _save_frame(engine, site_id, "prev", bands)
            results.append(_persist_observation(engine, site_id, scene, bands, anchor_idx, sr_method))
        with engine.begin() as c:
            c.execute(text("UPDATE sites SET backfill_status='done' WHERE id=:i"), {"i": site_id})
        return {"site_id": site_id, "status": "done" if len(scenes) >= 2 else "baseline_only",
                "scenes": len(results), "results": results}
    except Exception as exc:  # noqa: BLE001 — trace en base, jamais silencieux
        logger.exception("backfill site %s", site_id)
        with engine.begin() as c:
            c.execute(text("UPDATE sites SET backfill_status='error', backfill_error=:e WHERE id=:i"),
                      {"e": str(exc)[:500], "i": site_id})
        raise


def check_site(engine: Engine | None, site_id: int) -> dict:
    """Verification manuelle : scene la plus recente vs ancre t0 (ou baseline si 1re fois)."""
    engine = engine or _engine()
    site = _get_site(engine, site_id)
    polygon = json.loads(site["polygon_geojson"])
    ctx = StacContext()
    scenes = ctx.search_scenes(polygon, limit=1, window_days=settings.search_window_days)
    if not scenes:
        return {"site_id": site_id, "status": "cloud_pending"}
    bands, sr_method = upscale_bands(fetch_bands(ctx, polygon, scenes[0]))
    anchor = _load_frame_row(engine, site_id, "anchor")
    if anchor is None:
        _save_frame(engine, site_id, "anchor", bands)
        anchor_idx = None
    else:
        anchor_idx = _indices(anchor)
    _save_frame(engine, site_id, "prev", bands)
    result = _persist_observation(engine, site_id, scenes[0], bands, anchor_idx, sr_method)
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
