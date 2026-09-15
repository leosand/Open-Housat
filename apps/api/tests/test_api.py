"""Tests API — TestClient, SQLite isole, RFC 7807, validation bbox, compare. Sans reseau."""

import os

os.environ["HOUSAT_DATABASE_URL"] = "sqlite:///./test-housat.db"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)

VALID = {"name": "Chantier Demo", "owner_email": "demo@housat.app",
         "min_lon": 9.70, "min_lat": 4.04, "max_lon": 9.71, "max_lat": 4.05}


def test_healthz() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_create_site_ok_201() -> None:
    r = client.post("/sites", json=VALID)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] is not None and body["backfill_status"] == "idle"
    assert '"Polygon"' in body["polygon_geojson"]


def test_create_site_bbox_invalide_rfc7807() -> None:
    r = client.post("/sites", json={**VALID, "max_lon": 9.69})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_create_site_bbox_trop_grande() -> None:
    big = {**VALID, "max_lon": 9.9, "max_lat": 4.2}
    assert client.post("/sites", json=big).status_code == 422


def test_get_site_404_rfc7807() -> None:
    r = client.get("/sites/999999")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_progress_initial_idle() -> None:
    site_id = client.post("/sites", json={**VALID, "name": "Chantier B"}).json()["id"]
    p = client.get(f"/sites/{site_id}/progress").json()
    assert p["backfill_status"] == "idle"
    assert p["milestone"] is None
    assert p["observations"] == 0
    assert p["progression"] == 0.0


def test_compare_from_eq_to_422() -> None:
    site_id = client.get("/sites").json()[0]["id"]
    r = client.get(f"/sites/{site_id}/compare", params={"from": 1, "to": 1})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_compare_obs_inexistantes_404() -> None:
    site_id = client.get("/sites").json()[0]["id"]
    assert client.get(f"/sites/{site_id}/compare", params={"from": 1, "to": 2}).status_code == 404


def test_observations_vides_et_frames_vides() -> None:
    site_id = client.get("/sites").json()[0]["id"]
    assert client.get(f"/sites/{site_id}/observations").json() == []
    assert client.get(f"/sites/{site_id}/frames").json() == {"anchor": False, "prev": False}
