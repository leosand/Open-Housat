"""API Housat — FastAPI, erreurs RFC 7807, validation stricte.
Product API: register a site polygon, consult observations, trigger a manual check.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, SQLModel, create_engine, select

from models import Alert, Observation, Site

DATABASE_URL = "sqlite:///./housat-dev.db"  # surcharger par env en prod (PostGIS)
engine = create_engine(DATABASE_URL)

app = FastAPI(
    title="Housat API",
    version="0.1.0",
    description="Verification satellite de chantiers residentiels — Sentinel-2 + superresolution IA.",
)


@app.on_event("startup")
def on_startup() -> None:
    SQLModel.metadata.create_all(engine)


@app.exception_handler(HTTPException)
async def rfc7807_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Erreurs au format RFC 7807 (application/problem+json) / RFC 7807 problem details."""
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": str(exc.detail), "status": exc.status_code},
    )


def get_session() -> Session:  # type: ignore[return]
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class SiteIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    owner_email: EmailStr
    polygon: dict = Field(description="GeoJSON Polygon EPSG:4326 de la parcelle")
    cadence_days: int = Field(default=7, ge=5, le=30)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sites", status_code=status.HTTP_201_CREATED)
def create_site(body: SiteIn, session: SessionDep) -> Site:
    if body.polygon.get("type") != "Polygon":
        raise HTTPException(422, "polygon doit etre un GeoJSON Polygon")
    site = Site(
        name=body.name,
        owner_email=str(body.owner_email),
        polygon_geojson=json.dumps(body.polygon),
        cadence_days=body.cadence_days,
    )
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@app.get("/sites/{site_id}")
def get_site(site_id: int, session: SessionDep) -> Site:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    return site


@app.get("/sites/{site_id}/observations")
def list_observations(site_id: int, session: SessionDep, limit: int = 30) -> list[Observation]:
    if session.get(Site, site_id) is None:
        raise HTTPException(404, "chantier introuvable / site not found")
    return list(
        session.exec(
            select(Observation)
            .where(Observation.site_id == site_id)
            .order_by(Observation.created_at.desc())  # type: ignore[attr-defined]
            .limit(min(limit, 100))
        )
    )


@app.get("/sites/{site_id}/alerts")
def list_alerts(site_id: int, session: SessionDep) -> list[Alert]:
    return list(session.exec(select(Alert).where(Alert.site_id == site_id)))
