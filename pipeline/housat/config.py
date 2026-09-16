"""Configuration typee via variables d'environnement / Typed settings from env vars."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://housat:housat@localhost:5432/housat"
    stac_api_url: str = "https://earth-search.aws.element84.com/v1"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "housat-observations"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    ntfy_topic: str = "housat-dev"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_from: str = "alertes@housat.app"

    # Seuil NUAGE PAR PARCELLE (SCL) : une scene est exploitable si la PARCELLE est degagee,
    # meme si la TUILE Sentinel-2 (~110 km) est tres nuageuse.
    # Per-parcel cloud threshold (SCL): usable when the PARCEL is clear, not the tile.
    max_cloud_cover: float = 20.0
    # Pre-filtre STAC sur `eo:cloud_cover` (TUILE) — volontairement LARGE : ne jamais exclure en
    # amont une scene dont la parcelle serait degagee.
    tile_cloud_prefilter: float = 90.0
    search_window_days: int = 35
    change_threshold: float = 0.12

    # --- Surresolution / Super-resolution ---
    # Voie DETECTION (bandes radiometriques) : auto=sen2sr si installe sinon bicubique.
    # Detection track (radiometric bands): auto -> sen2sr when installed, else bicubic.
    sr_engine: str = "auto"          # auto | sen2sr | bicubic
    # Voie AFFICHAGE (PNG avant/apres) : modele perceptuel optionnel, jamais les indices.
    # Display track (before/after PNG): optional perceptual model, never the indices.
    display_sr_engine: str = "auto"  # auto | realesrgan | bicubic
    sr_model_path: str = ""          # chemin du modele .onnx Real-ESRGAN (voie affichage)
    sr_tile: int = 256               # taille de tuile pour l'inference ONNX (memoire bornee)
    sr_scale: int = 4                # facteur d'echelle du modele perceptuel

    # --- Fond visuel haute resolution / High-resolution visual basemap ---
    # Cle Planet (NICFI) : SERVEUR uniquement — jamais exposee au navigateur (tile service Planet).
    # Planet (NICFI) API key: SERVER-side only — never exposed to the browser.
    planet_api_key: str = ""
    # Mosaique NICFI datee (ex. planet_medres_normalized_analytic_2023-06_mosaic).
    nicfi_mosaic: str = ""


settings = Settings()
