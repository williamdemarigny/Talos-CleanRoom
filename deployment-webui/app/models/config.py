"""Configuration file models."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class NodeConfig(BaseModel):
    """Configuration for a single node."""
    name: str = Field(..., description="Node name")
    vmid: int = Field(..., ge=100, description="Proxmox VM ID")
    fqdn: str = Field(..., description="Fully qualified domain name")
    cores: int = Field(..., ge=1, description="Number of CPU cores")
    memory: int = Field(..., ge=512, description="Memory in MB")
    disk_size: str = Field(..., description="Disk size (e.g., '50G')")
    mac_address: str = Field(..., description="MAC address")
    tags: Optional[List[str]] = Field(default=None, description="Node tags")


class NetworkConfig(BaseModel):
    """Network configuration."""
    bridge: str = Field(default="vmbr0", description="Network bridge")
    vlan: Optional[int] = Field(default=None, description="VLAN ID")


class TerraformConfig(BaseModel):
    """Terraform cluster configuration."""
    nodes: List[NodeConfig] = Field(default_factory=list, description="Node definitions")
    network: NetworkConfig = Field(default_factory=NetworkConfig, description="Network config")
    storage: str = Field(default="local-lvm", description="Storage location")
    talos_iso_storage: str = Field(default="local", description="ISO storage location")
    talos_iso_file: str = Field(default="", description="Talos ISO filename")


class TalosEnvConfig(BaseModel):
    """Talos environment configuration from talenv.yaml."""
    talosVersion: Optional[str] = Field(default=None, description="Talos version")
    kubernetesVersion: Optional[str] = Field(default=None, description="Kubernetes version")
    clusterName: Optional[str] = Field(default=None, description="Cluster name")
    clusterEndpoint: Optional[str] = Field(default=None, description="Cluster API endpoint")
    clusterPodCIDRs: Optional[str] = Field(default=None, description="Pod network CIDR")
    clusterServiceCIDRs: Optional[str] = Field(default=None, description="Service network CIDR")


class TalosNodeDef(BaseModel):
    """Node definition in talconfig.yaml."""
    hostname: str
    ipAddress: str
    controlPlane: bool = False
    installDiskSelector: Optional[Dict[str, Any]] = None


class TalosClusterConfig(BaseModel):
    """Talos cluster configuration from talconfig.yaml."""
    clusterName: str
    talosVersion: str
    kubernetesVersion: str
    endpoint: str
    nodes: List[TalosNodeDef] = Field(default_factory=list)


class ConfigValidationResult(BaseModel):
    """Result of configuration validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
