"""Tests du rendu PDF hebdomadaire — pur, synthetique, sans reseau ni base."""

import json
from datetime import date

import numpy as np
from housat import observations as obs
from housat import reporting


def _png(seed: float) -> bytes:
    bands = {k: np.full((8, 8), seed + i * 0.05, dtype=np.float32)
             for i, k in enumerate(("red", "green", "blue", "nir", "swir16"))}
    return obs.image_png_rgb(bands)


def _obs(day: str, pv_sum: float, milestone: int = 2, with_img: bool = True) -> dict:
    payload = {"status": "ok", "milestone": milestone,
               "milestone_label": "structure en progression", "pivot_confirme": True,
               "confidence": 0.8, "emprise": 0.21, "pv_sum": pv_sum,
               "image_bbox": [9.70, 4.04, 9.71, 4.05]}
    return {"id": 1, "obs_date": day, "milestone": milestone, "pivot_confirme": True,
            "confidence": 0.8, "payload": json.dumps(payload),
            "image_png": _png(pv_sum) if with_img else None}


def test_week_bounds_iso() -> None:
    start, end = reporting.week_bounds(date(2026, 9, 16))  # mercredi
    assert start == date(2026, 9, 14) and end == date(2026, 9, 20)
    assert start.weekday() == 0 and end.weekday() == 6


def test_last_iso_week() -> None:
    start, end = reporting.last_iso_week(date(2026, 9, 15))  # mardi
    assert start == date(2026, 9, 7) and end == date(2026, 9, 13)


def test_week_kpis_progression() -> None:
    rows = [_obs("2026-09-08", 100.0), _obs("2026-09-10", 125.0)]
    kpi = reporting.week_kpis(rows)
    assert kpi["progression"] == 125.0
    assert kpi["pivot"] is True
    assert kpi["observations"] == 2


def test_render_pdf_bytes() -> None:
    rows = [_obs("2026-09-08", 100.0), _obs("2026-09-10", 125.0, with_img=False)]
    pdf = reporting.render_weekly_pdf(
        {"name": "Chantier Demo", "id": 1}, rows,
        [{"message": "Jalon atteint : structure en progression (M2)",
          "sent_at": "2026-09-10 08:00:00"}],
        date(2026, 9, 7), date(2026, 9, 13))
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 2000


def test_render_pdf_sans_images_ni_alertes() -> None:
    rows = [_obs("2026-09-08", 50.0, with_img=False)]
    pdf = reporting.render_weekly_pdf({"name": "Solo"}, rows, [],
                                      date(2026, 9, 7), date(2026, 9, 13))
    assert pdf[:5] == b"%PDF-"


def test_latin1_sanitize() -> None:
    assert reporting._latin1("ete") == "ete"
    assert reporting._latin1("ete — accentue, etc.") == "ete - accentue, etc."
    assert reporting._latin1("bulle • suite …") == "bulle - suite ..."
    # Latin-1 accepte les accents ; seuls les caracteres hors Latin-1 deviennent « ? ».
    assert reporting._latin1("ete \u00e9t\u00e9") == "ete \u00e9t\u00e9"
    assert "?" in reporting._latin1("emoji \U0001F3E0")
