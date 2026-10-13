"""API Housat MVP-l4 — FastAPI, RFC 7807, /compare avant-apres, overlays carte (MapLibre),
rapports PDF hebdomadaires persistes (reportlab, integrite sha256)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Annotated

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlmodel import Session, SQLModel, create_engine, select

from housat.reporting import (DuplicateReportError, NoObservationsError, SiteNotFoundError,
                              build_weekly_report, week_bounds)
from housat.worker import MILESTONE_LABELS_FR, backfill_site, check_site
from models import Alert, FrameStore, Observation, Report, Site, _iso_utc

logger = logging.getLogger("housat.api")

DATABASE_URL = os.environ.get("HOUSAT_DATABASE_URL", "sqlite:///./housat-dev.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}
                       if DATABASE_URL.startswith("sqlite") else {})

# Contenu immuable : id observation / (site, semaine) ne changent jamais apres ecriture.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

app = FastAPI(title="Housat API", version="0.5.4-mvp-l4",
              description="MVP : backfill, jalons V&V, avant/apres, carte, rapports PDF hebdo.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _init_db() -> None:
    """Idempotent : tables + dedup historique + index unique (SQLite + PG).

    V&V : les hooks de demarrage FastAPI ne s'executent pas avec un TestClient
    utilise sans gestionnaire de contexte — l'initialisation doit aussi exister
    a l'import pour que les tests et les workers partageant ce moteur soient sains.
    """
    SQLModel.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text(
            "DELETE FROM observations WHERE id NOT IN ("
            "SELECT MIN(id) FROM observations GROUP BY site_id, obs_date)"))
        c.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_site_date "
            "ON observations (site_id, obs_date)"))


_init_db()  # import-time : survive a TestClient sans lifespan


@app.on_event("startup")
def on_startup() -> None:
    _init_db()


@app.exception_handler(HTTPException)
async def rfc7807_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, media_type="application/problem+json",
                        content={"type": "about:blank", "title": str(exc.detail), "status": exc.status_code})


def get_session() -> Session:  # type: ignore[return]
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def bbox_to_polygon(minx: float, miny: float, maxx: float, maxy: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy],
                                                [minx, maxy], [minx, miny]]]}


class SiteIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    owner_email: str = Field(default="", max_length=254)
    min_lon: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    cadence_days: int = Field(default=7, ge=5, le=30)


def _validate_bbox(b: SiteIn) -> None:
    if b.min_lon >= b.max_lon or b.min_lat >= b.max_lat:
        raise HTTPException(422, "bbox invalide : min < max requis")
    if (b.max_lon - b.min_lon) * (b.max_lat - b.min_lat) > 0.005:
        raise HTTPException(422, "bbox trop grande pour le MVP (max ~2 km2)")


def _pv_sum(payload: str) -> float:
    return float(json.loads(payload or "{}").get("pv_sum", 0.0))


def _images_present(session: Session, site_id: int) -> set:
    """Ids d'observations avec image, SANS charger les BLOB (colonne deferree)."""
    return set(session.exec(
        select(Observation.id).where(Observation.site_id == site_id,
                                     Observation.image_png.is_not(None))))  # type: ignore[union-attr]


def _iso_day(v: date | datetime) -> str:
    """Jour ISO, que l'entree soit un `date` ou un `datetime` (selon l'item STAC).

    Garde-fou : `date` n'a PAS de methode `.date()` — l'appeler levait un 500 sur /overpasses.
    """
    return (v.date() if isinstance(v, datetime) else v).isoformat()


def _summary(o: Observation, has_image: bool) -> dict:
    p = json.loads(o.payload or "{}")
    return {"id": o.id, "obs_date": o.obs_date, "milestone": o.milestone,
            "milestone_label": p.get("milestone_label"), "pivot_confirme": o.pivot_confirme,
            "confidence": o.confidence, "emprise": p.get("emprise"), "pv_sum": p.get("pv_sum"),
            "built_ratio": p.get("built_ratio"), "delta_ndbi": p.get("delta_ndbi"),
            "sr_method": p.get("sr_method"), "display_sr": p.get("display_sr"),
            "image_bbox": p.get("image_bbox"),
            "image_url": f"/observations/{o.id}/image" if has_image else None}


def _parse_week(week: str) -> date:
    """Valide une semaine ISO : lundi YYYY-MM-DD, semaine cloturee (pas en cours/future)."""
    try:
        d = date.fromisoformat(week)
    except ValueError as exc:
        raise HTTPException(422, "week doit etre une date ISO YYYY-MM-DD") from exc
    if d.weekday() != 0:
        raise HTTPException(422, "week doit tomber un lundi (debut de semaine ISO)")
    monday, _ = week_bounds(date.today())
    if d >= monday:
        raise HTTPException(422, "semaine ISO non cloturee (en cours ou future)")
    return d


def _report_meta(r: Report) -> dict:
    return {"id": r.id, "week_start": r.week_start, "week_end": r.week_end,
            "observations": r.observations_count, "sha256": r.sha256,
            "created_at": _iso_utc(r.created_at),
            "pdf_url": f"/sites/{r.site_id}/reports/{r.week_start}/pdf"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sr/preview")
def sr_preview(
    bbox: Annotated[str, Query(description="minLon,minLat,maxLon,maxLat")],
    size: int = Query(384, ge=128, le=768),
    model: str = Query("perceptual", pattern="^(perceptual|l1)$",
                       description="perceptual (LPIPS, defaut affichage) | l1 (fidelite PSNR)"),
) -> Response:
    """Apercu visuel de la surresolution d'affichage — pour TOUTE emprise lat/long.

    Renvoie un PNG a trois panneaux : **[LR ~10 m | SR ONNX (x4) | HR natif Esri]**. Le LR est
    simule a partir du fond haute resolution (moyennage d'aire, façon Sentinel-2) ; la SR est le
    modele ONNX servi (`SR_MODEL_PATH`) ; le HR est la source native (plafond de detail).
    Test navigateur direct, sans dependance aux scenes Sentinel-2 ni a la base.
    """
    import io

    from PIL import Image, ImageDraw

    from housat.benchmark import lanczos_resize, to_u8
    from housat.config import settings
    from housat.imagery.basemap import fetch_basemap, validate_bbox
    from housat.imagery.super_resolution import OnnxSrBackend

    try:
        b = validate_bbox(tuple(float(v) for v in bbox.split(",")))  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"bbox invalide: {exc}") from exc

    native = np.asarray(Image.open(io.BytesIO(fetch_basemap(b, size=size * 2,
                                                            provider="esri_world_imagery").data)).convert("RGB"))
    hr = lanczos_resize(native, size)
    lr_size = max(1, size // 4)
    lr = np.asarray(Image.fromarray(hr).resize((lr_size, lr_size), Image.BOX))       # LR simule ~10 m
    lr01 = lr.astype(np.float32) / 255.0
    base_dir = os.path.dirname(settings.sr_model_path) if settings.sr_model_path else ""
    fname = {"perceptual": "housat_sr_x4.onnx", "l1": "housat_sr_l1_x4.onnx"}[model]
    model_path = os.path.join(base_dir, fname) if base_dir else ""
    sr = None
    if model_path and os.path.exists(model_path):
        try:
            up = OnnxSrBackend(model_path, scale=settings.sr_scale,
                               tile=settings.sr_tile).upscale(lr01)
            sr = to_u8(up)
        except Exception:  # noqa: BLE001 — degradation honnete : repli bicubique trace
            logger.warning("SR ONNX indisponible dans /sr/preview", exc_info=True)
    if sr is None:
        sr = np.asarray(Image.fromarray(lr).resize((size, size), Image.LANCZOS))

    panels = [("LR ~10 m (sentinel-like)", np.asarray(Image.fromarray(lr).resize((size, size), Image.NEAREST))),
              (f"SR ONNX x4 ({model})", sr),
              ("HR natif (Esri)", hr)]
    label_h, pad = 20, 6
    total_w = size * len(panels) + pad * (len(panels) + 1)
    plate = Image.new("RGB", (total_w, size + label_h + pad * 2), (24, 24, 28))
    draw = ImageDraw.Draw(plate)
    x = pad
    for label, img in panels:
        plate.paste(Image.fromarray(img), (x, label_h + pad))
        draw.text((x + 2, 5), label, fill=(240, 240, 240))
        x += size + pad
    buf = io.BytesIO()
    plate.save(buf, format="PNG", optimize=True)
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/parcel/wayback/dates")
def wayback_dates(bbox: Annotated[str, Query(description="minLon,minLat,maxLon,maxLat")]) -> dict:
    """Dates d'imagerie HR DATÉE (Esri Wayback) disponibles pour l'emprise.

    Sert a choisir un vrai avant/apres OU l'on VOIT les batiments (sub-metrique), la ou
    Sentinel-2 (10 m) est illisible.
    """
    from housat.imagery.basemap import validate_bbox
    from housat.imagery.wayback import ATTRIBUTION, LICENCE, available_dates

    try:
        b = validate_bbox(tuple(float(v) for v in bbox.split(",")))  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"bbox invalide: {exc}") from exc
    return {"dates": available_dates(b), "attribution": ATTRIBUTION, "licence": LICENCE}


@app.get("/parcel/wayback/image")
def wayback_image(
    bbox: Annotated[str, Query(description="minLon,minLat,maxLon,maxLat")],
    date: Annotated[str, Query(description="date Wayback YYYY-MM-DD")],
    size: int | None = Query(None, ge=128, le=2048,
                             description="pixels ; omis = resolution NATIVE (nettete maximale)"),
) -> Response:
    """Image haute resolution (sub-metrique) de l'emprise a la date Wayback donnee.

    Pour superposer les emprises de batiments, utiliser `/parcel/buildings` (GeoJSON) et le moteur
    de carte : la rasterisation serveur faisait double emploi.
    """
    from housat.imagery.basemap import validate_bbox
    from housat.imagery.wayback import fetch_wayback

    try:
        b = validate_bbox(tuple(float(v) for v in bbox.split(",")))  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"bbox invalide: {exc}") from exc
    try:
        png = fetch_wayback(b, date, size=size)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": IMMUTABLE_CACHE})


@app.get("/parcel/wayback/tile")
def wayback_tile(
    date: Annotated[str, Query(description="date Wayback YYYY-MM-DD")],
    z: int, x: int, y: int,
) -> Response:
    """Proxy de tuile Wayback (même origine → pas de CORS ; URL Esri gardée côté serveur).

    Alimente MapLibre : le navigateur ne demande que les tuiles VISIBLES → rendu rapide + cache.
    """
    import httpx

    from housat.imagery.wayback import release_for

    rel = release_for(date)
    if rel is None:
        raise HTTPException(status_code=404, detail=f"date inconnue: {date}")
    try:
        r = httpx.get(rel.url(z, x, y), timeout=20.0, headers={"User-Agent": "Housat/1.0"},
                      follow_redirects=True)
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="tuile indisponible")
        png = r.content
        # Esri sert du JPEG : declarer image/png obligeait le navigateur a deviner (sniffing).
        media_type = r.headers.get("content-type", "image/jpeg").split(";")[0]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — tuile absente = 404 cote client (normal)
        raise HTTPException(status_code=404, detail="tuile indisponible") from exc
    return Response(content=png, media_type=media_type, headers={"Cache-Control": IMMUTABLE_CACHE})


@app.get("/parcel/buildings")
def parcel_buildings(bbox: Annotated[str, Query(description="minLon,minLat,maxLon,maxLat")]) -> dict:
    """Emprises de batiments (OSM/ODbL) en GeoJSON — superposition MapLibre (identifie le bati).

    `stats` caracterise l'emprise (nombre de batiments, part batie, emprise moyenne) ; `unavailable`
    dit qu'Overpass n'a pas repondu — a distinguer d'une zone reellement sans batiment cartographie.
    """
    from housat.imagery.basemap import validate_bbox
    from housat.imagery.buildings import ATTRIBUTION, fetch_buildings, footprint_stats

    try:
        b = validate_bbox(tuple(float(v) for v in bbox.split(",")))  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"bbox invalide: {exc}") from exc
    try:
        polys = fetch_buildings(b)
        stats = footprint_stats(polys, b)
    except Exception:  # noqa: BLE001 — Overpass sature : on le DIT au lieu d'un « 0 batiment »
        logger.warning("emprises OSM indisponibles", exc_info=True)
        polys, stats = [], None
    feats = [{"type": "Feature", "properties": {},
              "geometry": {"type": "Polygon",
                           "coordinates": [[list(p) for p in poly] + [list(poly[0])]]}}
             for poly in polys if len(poly) >= 3]
    return {"type": "FeatureCollection", "features": feats, "attribution": ATTRIBUTION,
            "stats": stats, "unavailable": stats is None}


@app.post("/sites", status_code=status.HTTP_201_CREATED)
def create_site(body: SiteIn, session: SessionDep) -> Site:
    _validate_bbox(body)
    poly = json.dumps(bbox_to_polygon(body.min_lon, body.min_lat, body.max_lon, body.max_lat))
    # Garde anti-doublon : plusieurs clics sur « Creer » ne doivent pas empiler des chantiers
    # IDENTIQUES (meme nom + meme emprise) — c'etait le cas : 5 « Ma maison » vides.
    existing = session.exec(select(Site).where(Site.name == body.name,
                                               Site.polygon_geojson == poly)).first()
    if existing is not None:
        raise HTTPException(status_code=409,
                            detail=f"chantier identique deja existant (id {existing.id}) — "
                                   "ouvrez-le dans la liste « Mes chantiers »")
    site = Site(name=body.name, owner_email=body.owner_email, polygon_geojson=poly,
                cadence_days=body.cadence_days)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@app.get("/sites")
def list_sites(session: SessionDep) -> list[dict]:
    """Liste des chantiers + **nombre d'observations** (distinguer un chantier exploite d'un vide)."""
    sites = list(session.exec(select(Site).order_by(Site.created_at.desc())))  # type: ignore[attr-defined]
    counts = dict(session.exec(
        select(Observation.site_id, func.count()).group_by(Observation.site_id)).all())
    return [{**s.model_dump(), "obs_count": int(counts.get(s.id, 0))} for s in sites]


@app.get("/sites/{site_id}")
def get_site(site_id: int, session: SessionDep) -> Site:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    return site


def _run_backfill_bg(site_id: int) -> None:
    from sqlalchemy import create_engine as ce
    backfill_site(ce(DATABASE_URL), site_id, limit=10)


@app.post("/sites/{site_id}/backfill", status_code=status.HTTP_202_ACCEPTED)
def trigger_backfill(site_id: int, background: BackgroundTasks, session: SessionDep) -> dict[str, str]:
    """Declenche le backfill. Le statut 'running' est pose ICI (transaction committee)
    avant d'accepter un second POST — evite la course idle/idle de deux 202 paralleles."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    if site.backfill_status == "running":
        raise HTTPException(409, "backfill deja en cours")
    site.backfill_status = "running"
    site.backfill_error = None
    session.add(site)
    session.commit()
    background.add_task(_run_backfill_bg, site_id)
    return {"status": "accepted", "poll": f"/sites/{site_id}/progress"}


@app.post("/sites/{site_id}/check")
def trigger_check(site_id: int, session: SessionDep) -> dict:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    try:
        return check_site(engine, site_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"echec verification : {exc}") from exc


@app.get("/sites/{site_id}/progress")
def progress(site_id: int, session: SessionDep) -> dict:
    """KPI du chantier. L'ordre est la date d'acquisition satellite (pas created_at) :
    un check d'une scene recente ne doit pas inverser first/last si une scene plus
    ancienne est reinseree plus tard."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    rows = list(session.exec(
        select(Observation).where(Observation.site_id == site_id)
        .order_by(Observation.obs_date.asc(), Observation.id.asc())))  # type: ignore[attr-defined]
    compared = [r for r in rows if json.loads(r.payload or "{}").get("status") == "ok"]
    latest_p = json.loads(rows[-1].payload if rows else "{}")
    # ETAPE = le plus haut jalon ATTEINT (meme regle monotone que les alertes) : une scene ulterieure
    # sans changement par rapport a l'ancre ne doit pas faire redescendre la fiche a « terrain nu »,
    # sinon elle contredit l'alerte « Etape franchie » deja envoyee au proprietaire.
    reached = [r for r in rows if r.milestone is not None]
    top = max(reached, key=lambda r: r.milestone) if reached else None
    top_p = json.loads(top.payload or "{}") if top is not None else {}
    anchor = rows[0] if rows else None
    pv_first = _pv_sum(compared[0].payload) if compared else 0.0
    pv_last = _pv_sum(compared[-1].payload) if compared else 0.0
    progression = round(100.0 * min(pv_last / max(pv_first, 1e-6), 1.3), 1) if pv_first > 0 else 0.0
    return {
        "backfill_status": site.backfill_status, "backfill_error": site.backfill_error,
        "milestone": top.milestone if top is not None else None,
        "milestone_label": (top_p.get("milestone_label")
                            or MILESTONE_LABELS_FR.get(top.milestone)) if top is not None else None,
        "pivot_confirme": bool(top_p.get("pivot_confirme", False)),
        # PREUVE de l'etape : la date qui l'a etablie et les deux nombres qui l'ont produite
        # (part de l'emprise en changement robuste + intensite), mesures contre l'image d'ancrage.
        "milestone_date": top.obs_date if top is not None else None,
        "milestone_emprise": top_p.get("emprise"),
        "milestone_pv": top_p.get("pv_sum"),
        # Signal d'ETAT du classifieur de jalon : la part de bati de la parcelle, a cote de
        # l'intensite de changement. C'est ce qui distingue une dalle brute d'une toiture posee
        # (`built_ratio` >= 0,4 + plateau NDBI = toiture) — sans lui, le rail ne prouve rien.
        "milestone_built_ratio": top_p.get("built_ratio"),
        "anchor_date": anchor.obs_date if anchor is not None else None,
        "pv_sum_first": pv_first, "pv_sum_last": pv_last,
        "delta_pra": latest_p.get("croissance"), "progression": progression,
        "observations": len(rows),
    }


@app.get("/sites/{site_id}/compare")
def compare(site_id: int, session: SessionDep,
            from_id: int = Query(alias="from"), to_id: int = Query(alias="to")) -> dict:
    """Comparaison avant/apres (meme chantier, grilles alignees, coins d'image pour la carte)."""
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    if from_id == to_id:
        raise HTTPException(422, "from et to doivent etre deux observations distinctes")
    a, b = session.get(Observation, from_id), session.get(Observation, to_id)
    if a is None or b is None or a.site_id != site_id or b.site_id != site_id:
        raise HTTPException(404, "observation introuvable pour ce chantier")
    va, vb = _pv_sum(a.payload), _pv_sum(b.payload)
    progression = round(100.0 * min(vb / max(va, 1e-6), 1.3), 1) if va > 0 else 0.0
    present = _images_present(session, site_id)
    return {"from": _summary(a, a.id in present), "to": _summary(b, b.id in present),
            "delta": {"progression": progression,
                      "milestone_from": a.milestone, "milestone_to": b.milestone,
                      "pivot_confirme": b.pivot_confirme}}


@app.get("/sites/{site_id}/observations")
def list_observations(site_id: int, session: SessionDep, limit: int = 60) -> list[dict]:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    rows = session.exec(select(Observation).where(Observation.site_id == site_id)
                        .order_by(Observation.obs_date.desc(), Observation.id.desc()).limit(min(limit, 100)))  # type: ignore[attr-defined]
    present = _images_present(session, site_id)
    return [_summary(o, o.id in present) for o in rows]


@app.get("/observations/{obs_id}/image")
def observation_image(obs_id: int, session: SessionDep) -> Response:
    o = session.get(Observation, obs_id)
    if o is None or o.image_png is None:
        raise HTTPException(404, "image introuvable")
    return Response(content=bytes(o.image_png), media_type="image/png",
                    headers={"Cache-Control": IMMUTABLE_CACHE})


@app.get("/sites/{site_id}/alerts")
def list_alerts(site_id: int, session: SessionDep) -> list[Alert]:
    # `sent_at` est serialise AVEC fuseau par le modele (cf. models._iso_utc) -> heure locale correcte.
    return list(session.exec(select(Alert).where(Alert.site_id == site_id)
                             .order_by(Alert.sent_at.desc())))  # type: ignore[attr-defined]


@app.get("/sites/{site_id}/overpasses")
def site_overpasses(site_id: int, session: SessionDep, days: int = Query(120, ge=10, le=365),
                    limit: int = Query(60, ge=5, le=200),
                    parcel: bool = Query(False, description="calculer le nuage PAR PARCELLE (SCL) — plus lent")) -> dict:
    """Passages Sentinel-2 sur la parcelle : cadence REELLE de la constellation.

    Repond a « quelle est la frequence d'imagerie disponible ? » en listant **tous** les passages
    (y compris ceux ecartes par les nuages), avec leur statut d'analyse. Sentinel-2 revisite tous
    les ~5 jours ; le filtre de nuages reduit ce que le produit peut exploiter.
    """
    from housat.config import settings
    from housat.imagery.sentinel2 import StacContext

    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    polygon = json.loads(site.polygon_geojson)
    ctx = StacContext()
    try:
        scenes = ctx.search_scenes(polygon, limit=limit, max_cloud=100.0,
                                   window_days=days, mode="archive")
    except Exception as exc:  # noqa: BLE001 — catalogue indisponible : la page ne doit pas casser
        logger.warning("STAC indisponible pour la liste des passages", exc_info=True)
        raise HTTPException(503, f"catalogue STAC indisponible: {exc}") from exc

    ingested = {o.obs_date for o in session.exec(
        select(Observation).where(Observation.site_id == site_id))}
    rows = [{"date": _iso_day(s.acquired),
             "cloud_cover": round(float(s.cloud_cover), 1),
             "analysed": _iso_day(s.acquired) in ingested,
             "usable": float(s.cloud_cover) <= settings.max_cloud_cover} for s in scenes]

    if parcel:
        # Nuage PAR PARCELLE : un telechargement SCL par scene -> borne aux plus RECENTES.
        from housat.imagery.clouds import parcel_cloud_pct
        from housat.imagery.sentinel2 import fetch_scl

        by_date = {_iso_day(s.acquired): s for s in scenes}
        recent = sorted(by_date)[-12:]
        computed = 0
        for r in rows:
            if r["date"] not in recent:
                continue
            try:
                scl = fetch_scl(ctx, polygon, by_date[r["date"]])
                r["parcel_cloud_pct"] = (round(parcel_cloud_pct(scl), 1)
                                         if scl is not None else None)
            except Exception:  # noqa: BLE001 — mesure best-effort, jamais bloquante
                logger.warning("nuage parcelle indisponible pour %s", r["date"], exc_info=True)
                r["parcel_cloud_pct"] = None
            computed += 1
    else:
        computed = 0

    rows.sort(key=lambda r: r["date"])
    dts = [date.fromisoformat(r["date"]) for r in rows]
    gaps = sorted((b - a).days for a, b in zip(dts, dts[1:]))
    clear = [r for r in rows if r.get("parcel_cloud_pct") is not None
             and r["parcel_cloud_pct"] <= settings.max_cloud_cover]
    return {"site_id": site_id, "days": days, "max_cloud": settings.max_cloud_cover,
            "count": len(rows), "median_gap_days": gaps[len(gaps) // 2] if gaps else None,
            "parcel_clear_count": len(clear) if parcel else None,
            "parcel_computed": computed if parcel else None,
            "overpasses": rows}


@app.get("/sites/{site_id}/frames")
def frames_state(site_id: int, session: SessionDep) -> dict:
    rows = session.exec(select(FrameStore.kind).where(FrameStore.site_id == site_id))
    kinds = sorted(set(rows))
    return {"anchor": "anchor" in kinds, "prev": "prev" in kinds}


@app.get("/sites/{site_id}/reports")
def list_reports(site_id: int, session: SessionDep) -> list[dict]:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    rows = session.exec(select(Report).where(Report.site_id == site_id)
                        .order_by(Report.week_start.desc()))  # type: ignore[attr-defined]
    return [_report_meta(r) for r in rows]


@app.get("/sites/{site_id}/reports/{week}/pdf")
def report_pdf(site_id: int, week: str, session: SessionDep) -> Response:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    d = _parse_week(week)
    r = session.exec(select(Report).where(Report.site_id == site_id,
                                          Report.week_start == d.isoformat())).first()
    if r is None:
        raise HTTPException(404, "rapport introuvable pour cette semaine")
    return Response(content=bytes(r.pdf), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="housat-{site_id}-{r.week_start}.pdf"',
                             "ETag": f'"{r.sha256}"',
                             "Cache-Control": IMMUTABLE_CACHE})


def _parcel_hr_image(site: Site, until: date, size: int = 900) -> tuple[bytes | None, str]:
    """Vue HAUTE RESOLUTION de la parcelle (imagerie d'archive <= `until`) pour un PDF lisible.

    Best-effort : toute indisponibilite renvoie (None, "") — le rapport reste genere (voie mesure).
    Desactivable par `HOUSAT_REPORT_HR_IMAGE=0` : les tests doivent rester **sans reseau**, et un
    deploiement sans acces a l'archive doit pouvoir couper cet appel.
    """
    if os.environ.get("HOUSAT_REPORT_HR_IMAGE", "1") == "0":
        return None, ""
    try:
        from shapely.geometry import shape

        from housat.imagery.basemap import validate_bbox
        from housat.imagery.wayback import ATTRIBUTION, fetch_wayback, latest_date_at_or_before

        b = validate_bbox(tuple(shape(json.loads(site.polygon_geojson)).bounds))
        d = latest_date_at_or_before(b, until.isoformat())
        if d is None:
            return None, ""
        return fetch_wayback(b, d, size=size), (
            f"Image de votre parcelle : archive la plus recente disponible ({d}) - {ATTRIBUTION}")
    except Exception:  # noqa: BLE001 — best-effort : jamais bloquant pour le rapport
        logger.warning("vue HR indisponible pour le rapport", exc_info=True)
        return None, ""


@app.post("/sites/{site_id}/reports/{week}", status_code=status.HTTP_201_CREATED)
def generate_report(site_id: int, week: str, session: SessionDep) -> dict:
    """Generation manuelle d'un rapport hebdo (idempotent : 409 si deja genere)."""
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    d = _parse_week(week)
    # Verifier d'abord (cout nul, base locale) qu'il y a bien des observations : inutile de
    # chercher une image d'archive — donc du reseau — pour une semaine vide.
    week_end = d + timedelta(days=6)
    has_obs = session.exec(select(Observation.id).where(
        Observation.site_id == site_id,
        Observation.obs_date >= d.isoformat(),
        Observation.obs_date < week_end.isoformat())).first()
    if has_obs is None:
        raise HTTPException(422, "aucune observation cette semaine — lancez d'abord le backfill "
                                "(bouton en haut du chantier)")
    hr_png, hr_label = _parcel_hr_image(site, week_end)
    try:
        build_weekly_report(engine, site_id, d, hr_png, hr_label)
    except DuplicateReportError as exc:
        raise HTTPException(409, "rapport deja genere pour cette semaine") from exc
    except NoObservationsError as exc:
        raise HTTPException(422, "aucune observation sur cette semaine") from exc
    except SiteNotFoundError as exc:
        raise HTTPException(404, "chantier introuvable / site not found") from exc
    r = session.exec(select(Report).where(Report.site_id == site_id,
                                          Report.week_start == d.isoformat())).first()
    if r is None:
        raise HTTPException(500, "rapport genere mais illisible")
    return _report_meta(r)
