"""Modeles SQLModel MVP-l4 / Data models — PostGIS en prod, SQLite en dev local."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel


class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    owner_email: str = Field(default="", max_length=254)
    polygon_geojson: str
    status: str = Field(default="active", index=True)
    cadence_days: int = Field(default=7)
    backfill_status: str = Field(default="idle")   # idle | running | done | error
    backfill_error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Observation(SQLModel, table=True):
    __tablename__ = "observations"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    obs_date: str = Field(default="", index=True)  # date d'acquisition satellite ISO
    milestone: Optional[int] = Field(default=None)
    pivot_confirme: bool = Field(default=False)
    confidence: float = Field(default=0.0)
    payload: str = Field(default="")               # JSON indicateurs + scene
    image_png: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    channel: str = Field(default="in-app")         # in-app en MVP-l1 ; ntfy/email/WhatsApp ensuite
    message: str
    milestone: Optional[int] = Field(default=None)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FrameStore(SQLModel, table=True):
    __tablename__ = "frame_store"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    kind: str = Field(index=True)                  # anchor (t0) | prev (derniere)
    data: bytes = Field(sa_column=Column(LargeBinary))


class Report(SQLModel, table=True):
    """Rapport PDF hebdomadaire persiste — un par (chantier, semaine ISO)."""
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("site_id", "week_start", name="uq_report_site_week"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    week_start: str = Field(index=True)            # lundi ISO YYYY-MM-DD
    week_end: str                                  # dimanche ISO YYYY-MM-DD
    sha256: str = Field(max_length=64)             # integrite du PDF (ETag)
    observations_count: int = Field(default=0)
    pdf: bytes = Field(sa_column=Column(LargeBinary))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
