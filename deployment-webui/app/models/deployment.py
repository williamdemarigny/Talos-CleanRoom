"""Deployment state models."""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class StepStatus(str, Enum):
    """Status of a deployment step."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeploymentStep(BaseModel):
    """A single deployment step."""
    id: int
    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class DeploymentStatus(str, Enum):
    """Overall deployment status."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class DeploymentState(BaseModel):
    """Current state of a deployment."""
    id: str
    status: DeploymentStatus = DeploymentStatus.IDLE
    current_step: int = 0
    steps: List[DeploymentStep] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class LogEntry(BaseModel):
    """A log entry from deployment."""
    timestamp: datetime
    step_id: int
    level: str  # info, warn, error
    message: str


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str  # step_update, log, error, completion, abort
    timestamp: datetime
    data: dict


# Define all deployment steps
DEPLOYMENT_STEPS = [
    DeploymentStep(id=0, name="validate_git", description="Validate Git Repository"),
    DeploymentStep(id=1, name="check_dependencies", description="Check Dependencies"),
    DeploymentStep(id=2, name="terraform_deploy", description="Terraform Deploy"),
    DeploymentStep(id=3, name="wait_for_vms", description="Wait for VMs to Boot"),
    DeploymentStep(id=4, name="generate_talos_config", description="Generate Talos Config"),
    DeploymentStep(id=5, name="apply_talos_configs", description="Apply Talos Configurations"),
    DeploymentStep(id=6, name="verify_cluster_health", description="Verify Cluster Health"),
    DeploymentStep(id=7, name="get_kubeconfig", description="Get Kubeconfig"),
    DeploymentStep(id=8, name="install_argocd", description="Install ArgoCD"),
    DeploymentStep(id=9, name="deploy_infrastructure", description="Deploy Infrastructure Stack"),
    DeploymentStep(id=10, name="argocd_self_management", description="Enable ArgoCD Self-Management"),
    DeploymentStep(id=11, name="deploy_openvas", description="Deploy OpenVAS"),
    DeploymentStep(id=12, name="deploy_faraday", description="Deploy Faraday"),
    DeploymentStep(id=13, name="deploy_metasploit", description="Deploy Metasploit"),
    DeploymentStep(id=14, name="deploy_threat_dragon", description="Deploy Threat Dragon"),
]
