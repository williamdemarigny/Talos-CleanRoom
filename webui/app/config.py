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
    repo_root: Path = Path("/opt/talos-cleanroom")

    # Deployment
    master_node: str = "10.83.3.10"
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

    # Build VM (LXC container for Docker image builds)
    build_vm_ip: str = "10.83.3.191"
    build_vm_vmid: int = 201
    build_vm_ssh_user: str = "deploy"
    build_vm_gateway: str = "10.83.3.1"
    build_vm_vlan_id: int = 3

    # Proxmox SSH (for pct exec during Build VM setup)
    proxmox_host: str = "pve01.knowledgeondemand.net"
    proxmox_ssh_user: str = "root"

    # Credentials file path (reuse cluster-create credentials)
    credentials_tfvars_path: str = "terraform/cluster-create/credentials.auto.tfvars"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
