"""Modeles SQLModel / Data models — PostGIS en production, SQLite possible en dev."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    owner_email: str = Field(index=True, max_length=254)
    polygon_geojson: str                      # polygone parcelle, EPSG:4326, <= ~1 km2 en v0.1
    status: str = Field(default="active", index=True)  # active | paused | closed
    cadence_days: int = Field(default=7)      # frequence de verification
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    prev_features_json: Optional[str] = None  # features precedentes (dettes v0.1, cf. roadmap)


class Observation(SQLModel, table=True):
    __tablename__ = "observations"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    payload: str                              # JSON : scene, scores, jalon, confiance
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", index=True)
    channel: str                              # ntfy | email | whatsapp (phase 2)
    message: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
