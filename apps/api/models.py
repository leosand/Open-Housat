"""Modeles SQLModel MVP-l1 / Data models — PostGIS en prod, SQLite en dev local."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, LargeBinary
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
