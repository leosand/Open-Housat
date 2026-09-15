"""Orchestrateur : traite tous les chantiers actifs, cron-able (GitHub Actions = 0 $).
Orchestrator: process every active site; designed for scheduled CI runs.
Usage : python -m housat.worker --once
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import create_engine

from housat.config import settings
from housat.imagery.sentinel2 import fetch_bands, search_best_scene
from housat.imagery.super_resolution import upscale_bands
from housat.detection.change import change_score
from housat.detection.milestones import Milestone, classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("housat.worker")

MILESTONE_LABELS_FR = {
    Milestone.M0_TERRAIN: "terrain nu",
    Milestone.M1_FONDATION: "fondation detectee",
    Milestone.M2_STRUCTURE: "structure en progression",
    Milestone.M3_TOITURE: "toiture probable",
    Milestone.M4_FINITION: "finition / amenagement",
}


def process_site(site: dict) -> dict:
    """Pipeline complet pour un chantier : scene -> SR -> changement -> jalon.
    Full per-site pipeline. Toute anomalie est tracee, jamais silencieuse (cf. failure modes).
    """
    polygon = json.loads(site["polygon_geojson"])
    scene = search_best_scene(polygon)
    if scene is None:
        logger.warning("site %s : aucune scene <= %.0f%% nuages", site["id"], settings.max_cloud_cover)
        return {"site_id": site["id"], "status": "cloud_pending"}

    bands = fetch_bands(polygon, scene)
    sr_bands, sr_method = upscale_bands(bands)

    result: dict = {
        "site_id": site["id"],
        "scene_id": scene.item_id,
        "acquired": scene.acquired.isoformat(),
        "cloud_cover": scene.cloud_cover,
        "sr_method": sr_method,
        "status": "ok",
    }

    if site.get("prev_features_json"):
        prev = json.loads(site["prev_features_json"])
        # NOTE v0.1 : features precedentes stockees compressees en base (voir roadmap dette technique)
        change = change_score(prev, sr_bands)  # type: ignore[arg-type]
        built_ratio = change.changed_pixels / max(change.total_pixels, 1)
        decision = classify(
            built_ratio=built_ratio,
            delta_ndbi_mean=change.delta_ndbi_mean,
            delta_bsi_mean=change.delta_bsi_mean,
            change_score_value=change.score,
            sr_method=sr_method,
        )
        result.update(
            change_score=round(change.score, 4),
            milestone=int(decision.milestone),
            milestone_label=MILESTONE_LABELS_FR[decision.milestone],
            confidence=decision.confidence,
            low_confidence=decision.low_confidence,
        )
    else:
        result["status"] = "baseline_created"  # 1re observation = reference bi-temporelle

    return result


def run_once() -> None:
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        sites = conn.execute(
            text("SELECT id, name, owner_email, polygon_geojson, prev_features_json "
                 "FROM sites WHERE status = 'active'")
        ).mappings().all()
        for site in sites:
            try:
                obs = process_site(dict(site))
                conn.execute(
                    text("INSERT INTO observations (site_id, payload, created_at) "
                         "VALUES (:sid, :payload, :ts)"),
                    {"sid": obs["site_id"], "payload": json.dumps(obs),
                     "ts": datetime.now(timezone.utc)},
                )
                logger.info("site %s -> %s", obs["site_id"], obs["status"])
            except Exception:  # noqa: BLE001 — isolation par site, erreur tracee
                logger.exception("echec traitement site %s", site["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Housat worker")
    parser.add_argument("--once", action="store_true", help="un seul passage (cron)")
    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        parser.error("v0.1 : seul --once est supporte (cron GitHub Actions)")


if __name__ == "__main__":
    main()
