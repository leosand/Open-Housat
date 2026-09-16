"""Tests API rapports PDF — TestClient, SQLite isole, aucune IO reseau."""

import json
from datetime import date, timedelta

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session

from housat import observations as obsmod
from housat.reporting import last_iso_week, week_bounds
from main import app, engine
from models import Observation

client = TestClient(app)

VALID = {"name": "Chantier Rapport", "owner_email": "",
         "min_lon": 9.70, "min_lat": 4.04, "max_lon": 9.71, "max_lat": 4.05}

MONDAY, SUNDAY = last_iso_week()


def _seed() -> int:
    """Cree un chantier + 2 observations dans la semaine ISO ecoulee."""
    site_id = client.post("/sites", json=VALID).json()["id"]
    png = obsmod.image_png_rgb({k: np.full((8, 8), 0.2 + i * 0.05, dtype=np.float32)
                                for i, k in enumerate(("red", "green", "blue", "nir", "swir16"))})
    payload = {"status": "ok", "milestone": 2, "milestone_label": "structure en progression",
               "pivot_confirme": True, "confidence": 0.8, "emprise": 0.21, "pv_sum": 123.4,
               "image_bbox": [9.70, 4.04, 9.71, 4.05]}
    with Session(engine) as s:
        for d in (0, 3):
            s.add(Observation(site_id=site_id, obs_date=(MONDAY + timedelta(days=d)).isoformat(),
                              milestone=2, pivot_confirme=True, confidence=0.8,
                              payload=json.dumps(payload), image_png=png))
        s.commit()
    return site_id


def test_cycle_complet_rapport_pdf() -> None:
    site_id = _seed()
    week = MONDAY.isoformat()

    r = client.post(f"/sites/{site_id}/reports/{week}")
    assert r.status_code == 201
    meta = r.json()
    assert meta["week_start"] == week and meta["week_end"] == SUNDAY.isoformat()
    assert meta["observations"] == 2 and len(meta["sha256"]) == 64

    dup = client.post(f"/sites/{site_id}/reports/{week}")
    assert dup.status_code == 409
    assert dup.headers["content-type"].startswith("application/problem+json")

    listing = client.get(f"/sites/{site_id}/reports").json()
    assert any(m["id"] == meta["id"] for m in listing)

    pdf = client.get(f"/sites/{site_id}/reports/{week}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    assert pdf.headers["etag"] == f'"{meta["sha256"]}"'


def test_rapport_semaine_sans_observation_422() -> None:
    site_id = client.post("/sites", json={**VALID, "name": "Chantier Vide"}).json()["id"]
    r = client.post(f"/sites/{site_id}/reports/{MONDAY.isoformat()}")
    assert r.status_code == 422


def test_rapport_week_invalide_422() -> None:
    site_id = client.post("/sites", json={**VALID, "name": "Chantier Dates"}).json()["id"]
    mercredi = (MONDAY + timedelta(days=2)).isoformat()
    assert client.post(f"/sites/{site_id}/reports/{mercredi}").status_code == 422
    en_cours = week_bounds(date.today())[0].isoformat()
    assert client.post(f"/sites/{site_id}/reports/{en_cours}").status_code == 422
    assert client.post(f"/sites/{site_id}/reports/pas-une-date").status_code == 422


def test_rapports_404_site_et_semaine() -> None:
    assert client.get("/sites/999998/reports").status_code == 404
    assert client.post(f"/sites/999998/reports/{MONDAY.isoformat()}").status_code == 404
    site_id = client.post("/sites", json={**VALID, "name": "Chantier 404"}).json()["id"]
    avant = (MONDAY - timedelta(days=7)).isoformat()
    assert client.get(f"/sites/{site_id}/reports/{avant}/pdf").status_code == 404
