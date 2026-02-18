"""Application configuration using Pydantic settings."""

from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Talos CleanRoom Deployment"
    debug: bool = False

    # Authentication
    admin_username: str = "admin"
    admin_password_hash: str = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4xL4FXvQsZI5EjBi"  # Default: admin
    secret_key: str = "change-this-in-production-use-openssl-rand-hex-32"
    access_token_expire_hours: int = 8

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
