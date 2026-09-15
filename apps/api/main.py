"""API Housat MVP-l4 — FastAPI, RFC 7807, /compare avant-apres, overlays carte (MapLibre),
rapports PDF hebdomadaires persistes (reportlab, integrite sha256)."""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from housat.reporting import (DuplicateReportError, NoObservationsError, SiteNotFoundError,
                              build_weekly_report, week_bounds)
from housat.worker import backfill_site, check_site
from models import Alert, FrameStore, Observation, Report, Site

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


def _summary(o: Observation, has_image: bool) -> dict:
    p = json.loads(o.payload or "{}")
    return {"id": o.id, "obs_date": o.obs_date, "milestone": o.milestone,
            "milestone_label": p.get("milestone_label"), "pivot_confirme": o.pivot_confirme,
            "confidence": o.confidence, "emprise": p.get("emprise"), "pv_sum": p.get("pv_sum"),
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
            "created_at": r.created_at.isoformat(),
            "pdf_url": f"/sites/{r.site_id}/reports/{r.week_start}/pdf"}


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
    pv_first = _pv_sum(compared[0].payload) if compared else 0.0
    pv_last = _pv_sum(compared[-1].payload) if compared else 0.0
    progression = round(100.0 * min(pv_last / max(pv_first, 1e-6), 1.3), 1) if pv_first > 0 else 0.0
    return {
        "backfill_status": site.backfill_status, "backfill_error": site.backfill_error,
        "milestone": latest_p.get("milestone"), "milestone_label": latest_p.get("milestone_label"),
        "pivot_confirme": bool(latest_p.get("pivot_confirme", False)),
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
    return list(session.exec(select(Alert).where(Alert.site_id == site_id)
                             .order_by(Alert.sent_at.desc())))  # type: ignore[attr-defined]


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


@app.post("/sites/{site_id}/reports/{week}", status_code=status.HTTP_201_CREATED)
def generate_report(site_id: int, week: str, session: SessionDep) -> dict:
    """Generation manuelle d'un rapport hebdo (idempotent : 409 si deja genere)."""
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    d = _parse_week(week)
    try:
        build_weekly_report(engine, site_id, d)
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
