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

    # Target Lab (Proxmox API for Metasploitable3 VMs)
    proxmox_api_url: str = ""
    proxmox_api_token: str = ""
    target_lab_enabled: bool = True
    target_vm_ttl_hours: int = 4
    target_vm_max_concurrent: int = 4
    target_vm_vmid_start: int = 5000
    target_vm_ip_start: str = "10.83.3.160"
    target_vm_ip_count: int = 10
    target_vm_vlan_id: int = 3
    target_vm_network_bridge: str = "vmbr0"
    target_vm_proxmox_node: str = ""
    target_vm_gateway: str = "10.83.3.1"
    target_vm_netmask: str = "255.255.255.0"
    metasploitable3_ubuntu_vmid: int = 4000
    metasploitable3_windows_vmid: int = 4001

    # Vulnerability enrichment (NVD/EPSS/OTX)
    enrichment_enabled: bool = True
    nvd_api_key: str = ""
    nvd_rate_limit: float = 6.5        # seconds between requests (no key)
    nvd_rate_limit_keyed: float = 0.7  # seconds between requests (with key)
    epss_enabled: bool = True
    otx_api_key: str = ""
    otx_enabled: bool = False
    enrichment_batch_size: int = 50
    enrichment_auto_trigger: bool = True
    enrichment_cache_ttl_days: int = 7
    enrichment_max_concurrent_nvd: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> ScanningSettings:
    """Get cached settings instance."""
    return ScanningSettings()
