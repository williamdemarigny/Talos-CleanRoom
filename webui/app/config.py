"""Application configuration using Pydantic settings.

Inherits shared auth/crypto fields from ``BaseAppSettings`` and adds
deployment-specific fields (repo_root, master_node, node_ips, etc.).
"""

from pathlib import Path
from functools import lru_cache

from talos_common.config_base import BaseAppSettings


class Settings(BaseAppSettings):
    """Deployment Console settings loaded from environment variables."""

    # Application
    app_name: str = "Talos CleanRoom Deployment"
    debug: bool = False

    # Repository
    repo_root: Path = Path("/repo")

    # Deployment
    master_node: str = "talos-CleanRoom-master-01.knowledgeondemand.net"
    health_check_retries: int = 30
    health_check_interval: int = 10

    # Node IPs for cleanup operations (DHCP reservations)
    # These are used to reset Talos nodes before Terraform destroy
    node_ips: list[str] = [
        "10.83.3.10",   # talos-CleanRoom-master-01
        "10.83.3.15",   # talos-CleanRoom-worker-01
        "10.83.3.16",   # talos-CleanRoom-worker-02
        "10.83.3.17",   # talos-CleanRoom-worker-03
    ]

    # Dependencies required for deployment
    dependencies: list[str] = [
        "terraform", "talhelper", "talosctl", "sops",
        "jq", "curl", "kubectl", "helm", "git"
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
