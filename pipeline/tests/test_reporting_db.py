"""Tests DB du rapport hebdo — sqlalchemy + SQLite en memoire, sans reseau."""

import json
from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from housat import observations as obs
from housat import reporting

MONDAY = date(2026, 9, 7)  # semaine ISO de reference


def _engine_seeded():
    eng = create_engine("sqlite:///:memory:")
    bands = {k: np.full((12, 12), 0.2 + i * 0.05, dtype=np.float32)
             for i, k in enumerate(("red", "green", "blue", "nir", "swir16"))}
    png = obs.image_png_rgb(bands)
    payload = json.dumps({"status": "ok", "milestone": 2,
                          "milestone_label": "structure en progression",
                          "pivot_confirme": True, "confidence": 0.8,
                          "emprise": 0.21, "pv_sum": 100.0})
    with eng.begin() as c:
        c.execute(text("CREATE TABLE sites (id INTEGER PRIMARY KEY, name VARCHAR(120),"
                       " status VARCHAR(32) DEFAULT 'active', created_at VARCHAR(32))"))
        c.execute(text("CREATE TABLE observations (id INTEGER PRIMARY KEY, site_id INTEGER,"
                       " obs_date VARCHAR(32), milestone INTEGER, pivot_confirme BOOLEAN,"
                       " confidence FLOAT, payload TEXT, image_png BLOB, created_at VARCHAR(32))"))
        c.execute(text("CREATE TABLE alerts (id INTEGER PRIMARY KEY, site_id INTEGER,"
                       " channel VARCHAR(32), message TEXT, milestone INTEGER, sent_at VARCHAR(32))"))
        c.execute(text("INSERT INTO sites (id, name) VALUES (1, 'Chantier T')"))
        for d in (0, 3):
            c.execute(text("INSERT INTO observations (site_id, obs_date, milestone,"
                           " pivot_confirme, confidence, payload, image_png, created_at)"
                           " VALUES (1, :d, 2, 1, 0.8, :p, :img, '2026-09-10 08:00:00')"),
                      {"d": (MONDAY + timedelta(days=d)).isoformat(), "p": payload, "img": png})
        c.execute(text("INSERT INTO alerts (site_id, channel, message, milestone, sent_at)"
                       " VALUES (1, 'in-app', 'Jalon atteint (M2)', 2, '2026-09-10 08:00:00')"))
    return eng


def test_build_weekly_report_persiste_pdf_integre() -> None:
    eng = _engine_seeded()
    meta = reporting.build_weekly_report(eng, 1, MONDAY)
    assert meta["observations_count"] == 2
    assert len(meta["sha256"]) == 64
    with eng.begin() as c:
        row = c.execute(text("SELECT week_start, week_end, pdf, sha256 FROM reports"
                             " WHERE site_id=1")).first()
    assert row[0] == MONDAY.isoformat() and row[1] == (MONDAY + timedelta(days=6)).isoformat()
    assert bytes(row[2])[:5] == b"%PDF-"
    assert row[3] == meta["sha256"]


def test_build_weekly_report_dedup_409() -> None:
    eng = _engine_seeded()
    reporting.build_weekly_report(eng, 1, MONDAY)
    with pytest.raises(reporting.DuplicateReportError):
        reporting.build_weekly_report(eng, 1, MONDAY)


def test_build_weekly_report_semaine_vide() -> None:
    eng = _engine_seeded()
    with pytest.raises(reporting.NoObservationsError):
        reporting.build_weekly_report(eng, 1, MONDAY - timedelta(days=7))


def test_build_weekly_report_gardes() -> None:
    eng = _engine_seeded()
    with pytest.raises(reporting.SiteNotFoundError):
        reporting.build_weekly_report(eng, 999, MONDAY)
    with pytest.raises(reporting.ReportError):
        reporting.build_weekly_report(eng, 1, MONDAY + timedelta(days=1))  # mardi


def test_weekly_reports_isolation_et_idempotence() -> None:
    eng = _engine_seeded()
    out = reporting.weekly_reports(eng, MONDAY)
    assert len(out) == 1
    assert reporting.weekly_reports(eng, MONDAY) == []  # deja present : ignore, pas d'echec
    assert reporting.weekly_reports(eng, MONDAY - timedelta(days=14)) == []  # semaine vide
