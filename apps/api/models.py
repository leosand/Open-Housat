"""Modeles SQLModel MVP-l4 / Data models — PostGIS en prod, SQLite en dev local.

V&V 2026-09-15 : les colonnes binaires (image_png, pdf) sont en chargement DIFFERE
(deferred) — sinon chaque liste (/observations, /reports) chargerait tous les BLOB
en memoire pour rien. La lecture explicite declenche un lazy-load ponctuel.
Correctif V&V : `Column(..., deferred=True)` n'est pas un argument accepte par
SQLAlchemy 2.x (ils sont reserves a `mapped_column`/`orm.deferred`) -> l'API ne
s'importait plus. Forme equivalente et portable : `orm.deferred(Column(...))`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import field_serializer
from sqlalchemy import Column, LargeBinary, UniqueConstraint, orm
from sqlmodel import Field, SQLModel


def _iso_utc(v: datetime | None) -> str | None:
    """ISO 8601 AVEC fuseau : les datetimes sont stockes en UTC mais naifs (SQLite) -> on
    retablit l'offset, sinon le client affiche l'heure UTC comme si c'etait du local."""
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    owner_email: str = Field(default="", max_length=254)
    polygon_geojson: str
    status: str = Field(default="active", index=True)
    cadence_days: int = Field(default=7)
    backfill_status: str = Field(default="idle")
    backfill_error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str | None:
        return _iso_utc(v)


class Observation(SQLModel, table=True):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("site_id", "obs_date", name="uq_obs_site_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    obs_date: str = Field(default="", index=True)
    milestone: Optional[int] = Field(default=None)
    pivot_confirme: bool = Field(default=False)
    confidence: float = Field(default=0.0)
    payload: str = Field(default="")
    image_png: Optional[bytes] = Field(default=None,
                                       sa_column=orm.deferred(Column(LargeBinary)))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str | None:
        return _iso_utc(v)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    channel: str = Field(default="in-app")
    message: str
    milestone: Optional[int] = Field(default=None)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("sent_at")
    def _ser_sent_at(self, v: datetime) -> str | None:
        return _iso_utc(v)


class FrameStore(SQLModel, table=True):
    __tablename__ = "frame_store"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    kind: str = Field(index=True)
    data: bytes = Field(sa_column=orm.deferred(Column(LargeBinary)))


class Report(SQLModel, table=True):
    """Rapport PDF hebdomadaire persiste — un par (chantier, semaine ISO)."""
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("site_id", "week_start", name="uq_report_site_week"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    week_start: str = Field(index=True)
    week_end: str
    sha256: str = Field(max_length=64)
    observations_count: int = Field(default=0)
    pdf: bytes = Field(sa_column=orm.deferred(Column(LargeBinary)))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str | None:
        return _iso_utc(v)
