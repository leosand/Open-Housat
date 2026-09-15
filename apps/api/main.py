"""API Housat MVP-l1 — FastAPI, RFC 7807, backfill 202 + polling, images PNG.
Product API: sites via bbox/GeoJSON, archive backfill, manual check, dashboard data.
"""

from __future__ import annotations

import json
import os
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from housat.worker import backfill_site, check_site
from models import Alert, FrameStore, Observation, Site

DATABASE_URL = os.environ.get("HOUSAT_DATABASE_URL", "sqlite:///./housat-dev.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}
                       if DATABASE_URL.startswith("sqlite") else {})

app = FastAPI(title="Housat API", version="0.2.0-mvp-l1",
              description="MVP-l1 : verification satellite de chantiers — backfill archive, jalons, V&V pivot.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def on_startup() -> None:
    SQLModel.metadata.create_all(engine)


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
    if (b.max_lon - b.min_lon) * (b.max_lat - b.min_lat) > 0.005:  # ~quelques km2 — cap MVP
        raise HTTPException(422, "bbox trop grande pour le MVP (max ~2 km2)")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sites", status_code=status.HTTP_201_CREATED)
def create_site(body: SiteIn, session: SessionDep) -> Site:
    _validate_bbox(body)
    site = Site(name=body.name, owner_email=body.owner_email,
                polygon_geojson=json.dumps(bbox_to_polygon(body.min_lon, body.min_lat,
                                                           body.max_lon, body.max_lat)),
                cadence_days=body.cadence_days)
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@app.get("/sites")
def list_sites(session: SessionDep) -> list[Site]:
    return list(session.exec(select(Site).order_by(Site.created_at.desc())))  # type: ignore[attr-defined]


@app.get("/sites/{site_id}")
def get_site(site_id: int, session: SessionDep) -> Site:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    return site


def _run_backfill_bg(site_id: int) -> None:
    """Tache de fond avec engine dedie (thread-separe, jamais la session HTTP)."""
    from sqlalchemy import create_engine as ce
    backfill_site(ce(DATABASE_URL), site_id, limit=10)


@app.post("/sites/{site_id}/backfill", status_code=status.HTTP_202_ACCEPTED)
def trigger_backfill(site_id: int, background: BackgroundTasks, session: SessionDep) -> dict[str, str]:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    if site.backfill_status == "running":
        raise HTTPException(409, "backfill deja en cours")
    background.add_task(_run_backfill_bg, site_id)
    return {"status": "accepted", "poll": f"/sites/{site_id}/progress"}


@app.post("/sites/{site_id}/check")
def trigger_check(site_id: int, session: SessionDep) -> dict:
    """Verification manuelle synchrone (threadpool) vs ancre t0."""
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    try:
        return check_site(engine, site_id)
    except Exception as exc:  # noqa: BLE001 — remonte en RFC 7807
        raise HTTPException(502, f"echec verification : {exc}") from exc


@app.get("/sites/{site_id}/progress")
def progress(site_id: int, session: SessionDep) -> dict:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    obs_rows = list(session.exec(
        select(Observation).where(Observation.site_id == site_id)
        .order_by(Observation.created_at.desc()).limit(2)))  # type: ignore[attr-defined]
    latest = json.loads(obs_rows[0].payload) if obs_rows else None
    payload0 = json.loads(obs_rows[1].payload) if len(obs_rows) > 1 else None
    pv0 = float(payload0.get("emprise", 0.0)) if payload0 else 0.0
    pv = float(latest.get("emprise", 0.0)) if latest else 0.0
    dpra = float(latest.get("croissance", 0.0)) if latest else 0.0
    progression = round(min((pv0 / max(pv, 1e-6)) * 100.0, 130.0), 1) if pv > 0 and pv0 > 0 else \
        round(min(pv * 100.0, 130.0), 1)
    return {
        "backfill_status": site.backfill_status,
        "backfill_error": site.backfill_error,
        "milestone": latest.get("milestone") if latest else None,
        "milestone_label": latest.get("milestone_label") if latest else None,
        "pivot_confirme": bool(latest.get("pivot_confirme")) if latest else False,
        "pv0": pv0, "pv": pv, "delta_pra": dpra, "progression": progression,
        "observations": len(obs_rows),
    }


@app.get("/sites/{site_id}/observations")
def list_observations(site_id: int, session: SessionDep, limit: int = 60) -> list[dict]:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    rows = session.exec(select(Observation).where(Observation.site_id == site_id)
                        .order_by(Observation.created_at.desc()).limit(min(limit, 100)))  # type: ignore[attr-defined]
    return [{"id": o.id, "obs_date": o.obs_date, "milestone": o.milestone,
             "pivot_confirme": o.pivot_confirme, "confidence": o.confidence,
             "payload": json.loads(o.payload or "{}"), "has_image": o.image_png is not None}
            for o in rows]


@app.get("/observations/{obs_id}/image")
def observation_image(obs_id: int, session: SessionDep) -> Response:
    o = session.get(Observation, obs_id)
    if o is None or o.image_png is None:
        raise HTTPException(404, "image introuvable")
    return Response(content=bytes(o.image_png), media_type="image/png")


@app.get("/sites/{site_id}/alerts")
def list_alerts(site_id: int, session: SessionDep) -> list[Alert]:
    return list(session.exec(select(Alert).where(Alert.site_id == site_id)
                             .order_by(Alert.sent_at.desc())))  # type: ignore[attr-defined]


@app.get("/sites/{site_id}/frames")
def frames_state(site_id: int, session: SessionDep) -> dict:
    rows = session.exec(select(FrameStore.kind).where(FrameStore.site_id == site_id))
    kinds = sorted(set(rows))
    return {"anchor": "anchor" in kinds, "prev": "prev" in kinds}
