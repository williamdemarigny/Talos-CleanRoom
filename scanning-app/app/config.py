"""Scanning Console application configuration."""

from functools import lru_cache

from talos_common.config_base import BaseAppSettings


class ScanningSettings(BaseAppSettings):
    """Scanning Console settings loaded from environment variables."""

    # Application
    app_name: str = "Talos CleanRoom Scanning Console"
    debug: bool = False

    # Database (in-cluster DNS, no NodePort)
    database_url: str = (
        "postgresql+asyncpg://cleanroom:changeme"
        "@cleanroom-db.cleanroom-db.svc.cluster.local:5432/cleanroom"
    )

    # Database pool
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Faraday integration
    faraday_sync_enabled: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> ScanningSettings:
    """Get cached settings instance."""
    return ScanningSettings()
