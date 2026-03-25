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

    # Vulnerability enrichment (NVD/EPSS/OTX)
    enrichment_enabled: bool = False
    nvd_api_key: str = ""
    nvd_rate_limit: float = 6.5        # seconds between requests (no key)
    nvd_rate_limit_keyed: float = 0.7  # seconds between requests (with key)
    epss_enabled: bool = True
    otx_api_key: str = ""
    otx_enabled: bool = False
    enrichment_batch_size: int = 50
    enrichment_auto_trigger: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> ScanningSettings:
    """Get cached settings instance."""
    return ScanningSettings()
