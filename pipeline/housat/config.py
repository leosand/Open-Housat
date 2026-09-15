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

    max_cloud_cover: float = 20.0
    search_window_days: int = 35
    change_threshold: float = 0.12


settings = Settings()
