"""Portal application configuration."""

from functools import lru_cache

from talos_common.config_base import BaseAppSettings


class PortalSettings(BaseAppSettings):
    """Portal settings loaded from environment variables."""

    app_name: str = "Talos CleanRoom Portal"
    debug: bool = False

    # Target app URLs for cross-domain auth redirects
    deployment_console_url: str = "https://10.83.3.190:8000"
    scanning_console_url: str = "https://scan.knowledgeondemand.net"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> PortalSettings:
    """Get cached settings instance."""
    return PortalSettings()
