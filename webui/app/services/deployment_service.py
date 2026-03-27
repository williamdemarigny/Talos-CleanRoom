"""Deployment service for orchestrating cluster deployment.

This module provides the DeploymentService class which orchestrates the
complete deployment of a Talos Kubernetes cluster including:
- Infrastructure provisioning via Terraform
- Talos configuration generation and application
- ArgoCD installation and GitOps setup
- Security tool deployment (OpenVAS, Faraday, Metasploit, Threat Dragon)
"""

import asyncio
import json
import logging
import re
import secrets
import subprocess
import uuid
import shutil
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable, List
from dataclasses import dataclass, field

from app.config import get_settings
from app.models.deployment import (
    DeploymentState, DeploymentStatus, DeploymentStep, StepStatus,
    LogEntry, DEPLOYMENT_STEPS
)
from app.services.process_manager import ProcessManager
from app.services.kubectl_utils import KubernetesHelper
from app.services.base_service import BaseServiceMixin


# =============================================================================
# Timing Constants (seconds)
# =============================================================================
# These constants control various wait times and retry intervals throughout
# the deployment process. Adjust based on your infrastructure performance.

VM_BOOT_INITIAL_DELAY = 180       # Initial wait for VMs to boot after Terraform
BOOT_DELAY_CHECK_INTERVAL = 30    # Interval for countdown during boot delay
PROXMOX_API_TIMEOUT = 10          # Timeout for Proxmox API requests
TALOS_API_CHECK_TIMEOUT = 15      # Timeout for Talos API health checks
ARGOCD_SYNC_WAIT = 10             # Wait time after ArgoCD sync operations
THREAT_DRAGON_SYNC_WAIT = 30      # Extra wait for Threat Dragon deployment

# Retry configuration
VM_READY_MAX_ATTEMPTS = 30        # Maximum attempts to check VM readiness
VM_READY_RETRY_INTERVAL = 10      # Seconds between VM readiness checks

# Persistent state file — survives webapp restarts, cleared only on cleanup
STATE_FILE = Path("/app/data/deployment_state.json")

# Log sanitization — precompiled patterns for redacting sensitive data
_REDACT_PATTERNS = [
    re.compile(r'(password|token|secret[-_]?key|api[-_]?token)[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'--from-literal=\S+=\S+'),
]

logger = logging.getLogger(__name__)


@dataclass
class DeploymentService(BaseServiceMixin):
    """Service for orchestrating cluster deployment.

    Uses BaseServiceMixin for shared patterns (k8s helper, poll_until).
    Uses KubernetesHelper for kubectl operations.
    """

    process_manager: ProcessManager = field(default_factory=ProcessManager)
    current_deployment: Optional[DeploymentState] = None
    log_callback: Optional[Callable[[LogEntry], Awaitable[None]]] = None
    step_callback: Optional[Callable[[DeploymentStep], Awaitable[None]]] = None
    logs: List[LogEntry] = field(default_factory=list)
    credentials: dict[str, dict[str, str]] = field(default_factory=dict)
    _cleanup_running: bool = field(default=False)

    def __post_init__(self):
        self._k8s_helper = KubernetesHelper(self.process_manager)
        settings = get_settings()
        self.repo_root = settings.repo_root
        self.master_node = settings.master_node
        self.health_check_retries = settings.health_check_retries
        self.health_check_interval = settings.health_check_interval
        self.dependencies = settings.dependencies
        self.node_ips = settings.node_ips
        self._load_state()

    def _get_fernet_key(self):
        """Derive a Fernet encryption key from the webapp's SECRET_KEY.

        Uses HMAC-SHA256 with domain separation via BaseAppSettings.fernet_key,
        ensuring the state-encryption key is distinct from JWT/code-exchange keys.
        """
        settings = get_settings()
        return settings.fernet_key

    def _save_state(self):
        """Persist full deployment state to disk (encrypted).

        Uses Fernet symmetric encryption keyed to the webapp's SECRET_KEY.
        Saves credentials, step statuses, and recent logs so the deployment
        can be resumed after a webapp restart or failure.
        """
        try:
            from cryptography.fernet import Fernet
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "credentials": self.credentials,
                "deployment_status": (
                    self.current_deployment.status.value
                    if self.current_deployment else None
                ),
                "deployment_id": (
                    self.current_deployment.id
                    if self.current_deployment else None
                ),
                "current_step": (
                    self.current_deployment.current_step
                    if self.current_deployment else 0
                ),
                "error_message": (
                    self.current_deployment.error_message
                    if self.current_deployment else None
                ),
                "started_at": (
                    self.current_deployment.started_at.isoformat()
                    if self.current_deployment and self.current_deployment.started_at
                    else None
                ),
                "completed_at": (
                    self.current_deployment.completed_at.isoformat()
                    if self.current_deployment and self.current_deployment.completed_at
                    else None
                ),
                "steps": [
                    {
                        "id": s.id, "name": s.name, "description": s.description,
                        "status": s.status.value,
                        "started_at": s.started_at.isoformat() if s.started_at else None,
                        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                        "error_message": s.error_message,
                    }
                    for s in (self.current_deployment.steps if self.current_deployment else [])
                ],
                "logs": [
                    {
                        "step_id": entry.step_id, "level": entry.level,
                        "message": entry.message,
                        "timestamp": entry.timestamp.isoformat(),
                    }
                    for entry in self.logs[-500:]
                ],
            }
            plaintext = json.dumps(state).encode()
            f = Fernet(self._get_fernet_key())
            STATE_FILE.write_bytes(f.encrypt(plaintext))
        except Exception:
            pass  # Non-fatal — credentials still work in memory

    def _load_state(self):
        """Restore full deployment state from disk (decrypted).

        Restores credentials, step statuses, and logs so the UI shows
        accurate state after a webapp restart and resume is possible.
        """
        try:
            from cryptography.fernet import Fernet, InvalidToken
            if STATE_FILE.exists():
                f = Fernet(self._get_fernet_key())
                ciphertext = STATE_FILE.read_bytes()
                plaintext = f.decrypt(ciphertext)
                state = json.loads(plaintext.decode())
                self.credentials = state.get("credentials", {})

                # Restore logs
                saved_logs = state.get("logs", [])
                self.logs = [
                    LogEntry(
                        step_id=entry["step_id"],
                        level=entry["level"],
                        message=entry["message"],
                        timestamp=datetime.fromisoformat(entry["timestamp"]),
                    )
                    for entry in saved_logs
                ]

                # Restore deployment state with full step info
                saved_status = state.get("deployment_status")
                if saved_status and not self.current_deployment:
                    # Rebuild steps from saved state or fresh from DEPLOYMENT_STEPS
                    saved_steps = state.get("steps", [])
                    if saved_steps:
                        steps = [
                            DeploymentStep(
                                id=s["id"], name=s["name"],
                                description=s["description"],
                                status=StepStatus(s["status"]),
                                started_at=(
                                    datetime.fromisoformat(s["started_at"])
                                    if s.get("started_at") else None
                                ),
                                completed_at=(
                                    datetime.fromisoformat(s["completed_at"])
                                    if s.get("completed_at") else None
                                ),
                                error_message=s.get("error_message"),
                            )
                            for s in saved_steps
                        ]
                    else:
                        steps = [DeploymentStep(**s.model_dump()) for s in DEPLOYMENT_STEPS]

                    self.current_deployment = DeploymentState(
                        id=state.get("deployment_id", "restored"),
                        status=DeploymentStatus(saved_status),
                        current_step=state.get("current_step", 0),
                        error_message=state.get("error_message"),
                        started_at=(
                            datetime.fromisoformat(state["started_at"])
                            if state.get("started_at") else datetime.utcnow()
                        ),
                        completed_at=(
                            datetime.fromisoformat(state["completed_at"])
                            if state.get("completed_at") else None
                        ),
                        steps=steps,
                    )
        except Exception:
            pass  # Non-fatal — start fresh if state file is corrupt or key changed

    def _clear_state(self):
        """Delete the persisted state file (called on cleanup)."""
        try:
            if STATE_FILE.exists():
                STATE_FILE.unlink()
        except Exception:
            pass

    def _resolve_master_node(self) -> str:
        """Resolve the control plane endpoint from cluster.auto.tfvars.

        Reads the ``ip`` field of the first controlplane node from the
        Terraform tfvars file.  Falls back to the ``master_node`` config
        setting (which may be a FQDN) if the file can't be parsed.
        """
        try:
            tfvars_path = self.repo_root / "terraform" / "cluster-create" / "cluster.auto.tfvars"
            if tfvars_path.exists():
                content = tfvars_path.read_text()
                # Find the controlplane node block and extract its ip field
                in_node = False
                is_controlplane = False
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("{"):
                        in_node = True
                        is_controlplane = False
                    elif stripped.startswith("}"):
                        in_node = False
                    elif in_node:
                        if 'role' in stripped and 'controlplane' in stripped:
                            is_controlplane = True
                        if is_controlplane and stripped.startswith("ip"):
                            # Parse:  ip  = "10.83.3.10",
                            m = re.search(r'ip\s*=\s*"([^"]+)"', stripped)
                            if m:
                                return m.group(1)
        except Exception:
            pass
        return self.master_node

    @property
    def terraform_dir(self) -> Path:
        return self.repo_root / "terraform" / "cluster-create"

    @property
    def talos_dir(self) -> Path:
        return self.repo_root / "cluster"

    @property
    def argocd_dir(self) -> Path:
        return self.repo_root / "apps" / "argocd"

    @property
    def projects_dir(self) -> Path:
        return self.repo_root / "apps"

    def _generate_password(self, length: int = 24) -> str:
        """Generate a cryptographically secure random password.

        Args:
            length: Length of the password to generate.

        Returns:
            A random alphanumeric password string.
        """
        alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def _sanitized_output_callback(self, step_id: int, level: str = "info"):
        """Return an on_output callback that sanitizes and logs.

        Redacts sensitive patterns (passwords, tokens) from log output
        before forwarding to the deployment log.
        """
        async def callback(line: str):
            sanitized = line
            for pattern in _REDACT_PATTERNS:
                sanitized = pattern.sub(
                    lambda m: m.group().split('=')[0] + '=***'
                    if '=' in m.group()
                    else m.group().split(':')[0] + ': ***',
                    sanitized,
                )
            await self.log(step_id, level, sanitized)
        return callback

    async def _create_secret(
        self,
        step_id: int,
        namespace: str,
        secret_name: str,
        data: dict[str, str]
    ) -> bool:
        """Create a Kubernetes secret if it doesn't already exist.

        Uses a temp file with ``kubectl apply -f`` instead of ``--from-literal``
        to avoid leaking secret values in process argument lists.

        Args:
            step_id: The deployment step identifier for logging.
            namespace: Kubernetes namespace for the secret.
            secret_name: Name of the secret to create.
            data: Dictionary of key-value pairs for the secret.

        Returns:
            True if secret exists or was created, False on error.
        """
        import base64
        import tempfile

        # Check if secret already exists
        check_result = await self.process_manager.run_command(
            ["kubectl", "get", "secret", secret_name, "-n", namespace],
            on_output=lambda _: None  # Suppress output
        )

        if check_result.success:
            await self.log(step_id, "info", f"Secret '{secret_name}' already exists in {namespace}")
            return True

        # Build secret manifest as JSON (kubectl accepts JSON via apply -f)
        secret_data = {
            k: base64.b64encode(v.encode()).decode() for k, v in data.items()
        }
        manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "namespace": namespace},
            "type": "Opaque",
            "data": secret_data,
        }

        # Write to temp file, apply, then clean up
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(manifest, f)
                temp_path = f.name

            result = await self.process_manager.run_command(
                ["kubectl", "apply", "-f", temp_path],
                on_output=lambda line: self.log(step_id, "info", line),
            )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        if result.success:
            await self.log(step_id, "info", f"Created secret '{secret_name}' in {namespace}")
        else:
            await self.log(step_id, "error", f"Failed to create secret '{secret_name}': {result.output}")

        return result.success

    async def _deploy_argocd_app(self, app_name: str, step_id: int) -> bool:
        """Apply an ArgoCD Application manifest and return success.

        Args:
            app_name: Name of the app directory under ``apps/``.
            step_id: The deployment step identifier for logging.
        """
        app_yaml = self.projects_dir / app_name / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._sanitized_output_callback(step_id),
        )
        if not result.success:
            await self.log(step_id, "error", f"Failed to apply ArgoCD app '{app_name}': {result.output}")
        return result.success

    async def _wait_for_argocd_sync(
        self,
        app_name: str,
        step_id: int,
        max_attempts: int = 30,
        interval: int = 10,
    ) -> bool:
        """Poll ArgoCD Application until synced.

        Args:
            app_name: ArgoCD Application name.
            step_id: The deployment step identifier for logging.
            max_attempts: Maximum number of polling attempts.
            interval: Seconds between polling attempts.

        Returns:
            True if the application reaches ``Synced`` status, False on timeout.
        """
        await self.log(step_id, "info", f"Waiting for ArgoCD to sync '{app_name}'...")

        for i in range(max_attempts):
            if self.current_deployment and self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            sync_result = await self.process_manager.run_command(
                ["kubectl", "get", "application", app_name, "-n", "argocd",
                 "-o", "jsonpath={.status.sync.status} {.status.health.status}"],
                timeout=15,
            )
            parts = (sync_result.output or "").strip().split()
            sync_status = parts[0] if len(parts) > 0 else ""
            health_status = parts[1] if len(parts) > 1 else ""

            if sync_status == "Synced":
                await self.log(
                    step_id, "info",
                    f"ArgoCD synced '{app_name}' (health: {health_status or 'unknown'})",
                )
                return True

            # Check for sync errors
            if sync_status in ("Unknown", "OutOfSync"):
                err_result = await self.process_manager.run_command(
                    ["kubectl", "get", "application", app_name, "-n", "argocd",
                     "-o", "jsonpath={.status.conditions[*].message}"],
                    timeout=15,
                )
                err_msg = (err_result.output or "").strip()
                if err_msg:
                    await self.log(step_id, "warn", f"ArgoCD sync issue: {err_msg[:300]}")

            await self.log(
                step_id, "info",
                f"ArgoCD: sync={sync_status or 'pending'} health={health_status or 'unknown'}... "
                f"({i + 1}/{max_attempts})",
            )
            await asyncio.sleep(interval)

        # Dump full ArgoCD application status for debugging
        await self.log(step_id, "error", f"ArgoCD failed to sync '{app_name}' after {max_attempts * interval}s")
        diag = await self.process_manager.run_command(
            ["kubectl", "get", "application", app_name, "-n", "argocd", "-o", "yaml"],
            timeout=15,
        )
        if diag.output:
            for line in diag.output.strip().split('\n')[-30:]:
                await self.log(step_id, "info", line)
        return False

    async def log(self, step_id: int, level: str, message: str):
        """Log a message and notify via callback."""
        entry = LogEntry(
            timestamp=datetime.utcnow(),
            step_id=step_id,
            level=level,
            message=message
        )
        await self._log_with_callback(entry, self.log_callback)

    async def update_step(self, step_id: int, status: StepStatus, error: Optional[str] = None):
        """Update step status and notify via callback."""
        if self.current_deployment:
            step = self.current_deployment.steps[step_id]
            step.status = status
            if status == StepStatus.RUNNING:
                step.started_at = datetime.utcnow()
            elif status in [StepStatus.SUCCESS, StepStatus.FAILED]:
                step.completed_at = datetime.utcnow()
            if error:
                step.error_message = error
            if self.step_callback:
                try:
                    await self.step_callback(step)
                except Exception:
                    pass  # Don't let broadcast failures crash the deployment

    def get_status(self) -> Optional[DeploymentState]:
        """Get current deployment status."""
        return self.current_deployment

    def is_running(self) -> bool:
        """Check if deployment or cleanup is currently running."""
        return (self._cleanup_running or
                (self.current_deployment is not None and
                 self.current_deployment.status == DeploymentStatus.RUNNING))

    async def start_deployment(
        self,
        log_callback: Optional[Callable[[LogEntry], Awaitable[None]]] = None,
        step_callback: Optional[Callable[[DeploymentStep], Awaitable[None]]] = None
    ) -> DeploymentState:
        """Start a new deployment."""
        if self.is_running():
            raise RuntimeError("Deployment already in progress")

        # Only update callbacks if new ones are provided (preserves WebSocket callbacks)
        if log_callback is not None:
            self.log_callback = log_callback
        if step_callback is not None:
            self.step_callback = step_callback
        self.logs = []
        self.credentials = {}

        # Initialize deployment state
        self.current_deployment = DeploymentState(
            id=str(uuid.uuid4()),
            status=DeploymentStatus.RUNNING,
            started_at=datetime.utcnow(),
            steps=[DeploymentStep(**s.model_dump()) for s in DEPLOYMENT_STEPS]
        )

        # Run deployment in background with error handling
        task = asyncio.create_task(self._run_deployment())
        task.add_done_callback(self._handle_task_exception)

        return self.current_deployment

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle unhandled exceptions from background deployment tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Background deployment task failed with unhandled exception: %s", exc, exc_info=exc)
            if self.current_deployment and self.current_deployment.status == DeploymentStatus.RUNNING:
                self.current_deployment.status = DeploymentStatus.FAILED
                self.current_deployment.completed_at = datetime.utcnow()

    async def abort_deployment(self) -> bool:
        """Abort the current deployment."""
        if not self.is_running():
            return False

        await self.process_manager.cancel()
        self.current_deployment.status = DeploymentStatus.ABORTED
        self.current_deployment.completed_at = datetime.utcnow()

        await self.log(
            self.current_deployment.current_step,
            "warn",
            "Deployment aborted by user"
        )

        return True

    async def resume_deployment(
        self,
        from_step: Optional[int] = None,
        log_callback: Optional[Callable[[LogEntry], Awaitable[None]]] = None,
        step_callback: Optional[Callable[[DeploymentStep], Awaitable[None]]] = None,
    ) -> DeploymentState:
        """Resume a failed or aborted deployment.

        Preserves existing logs and credentials. Re-runs from the failed step
        (or from ``from_step`` if specified).

        Args:
            from_step: Step ID to resume from. If None, resumes from the
                first non-successful step.
            log_callback: Optional async callback for log entries.
            step_callback: Optional async callback for step updates.

        Returns:
            The updated DeploymentState.

        Raises:
            RuntimeError: If no deployment exists to resume, or one is running.
        """
        if self.is_running():
            raise RuntimeError("Deployment already in progress")
        if not self.current_deployment:
            raise RuntimeError("No deployment to resume")
        if self.current_deployment.status not in (
            DeploymentStatus.FAILED, DeploymentStatus.ABORTED
        ):
            raise RuntimeError(
                f"Cannot resume deployment in state: {self.current_deployment.status.value}"
            )

        # Update callbacks
        if log_callback is not None:
            self.log_callback = log_callback
        if step_callback is not None:
            self.step_callback = step_callback

        # Determine resume point
        if from_step is None:
            # Find first non-successful step
            from_step = 0
            for step in self.current_deployment.steps:
                if step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                    from_step = step.id + 1
                else:
                    break

        # Reset the failed/running step so it can re-run
        for step in self.current_deployment.steps:
            if step.id >= from_step and step.status in (
                StepStatus.FAILED, StepStatus.RUNNING
            ):
                step.status = StepStatus.PENDING
                step.error_message = None
                step.started_at = None
                step.completed_at = None

        # Set deployment back to running
        self.current_deployment.status = DeploymentStatus.RUNNING
        self.current_deployment.error_message = None
        self.current_deployment.completed_at = None

        await self.log(-1, "info", f"Resuming deployment from step {from_step}...")

        # Run deployment in background from the resume point with error handling
        task = asyncio.create_task(self._run_deployment(resume_from_step=from_step))
        task.add_done_callback(self._handle_task_exception)

        return self.current_deployment

    async def skip_step(self, step_id: int) -> bool:
        """Mark a step as SKIPPED and resume from the next step.

        Args:
            step_id: The step to skip.

        Returns:
            True if the step was skipped and deployment resumed.
        """
        if self.is_running():
            raise RuntimeError("Cannot skip step while deployment is running")
        if not self.current_deployment:
            raise RuntimeError("No deployment exists")
        if step_id < 0 or step_id >= len(self.current_deployment.steps):
            raise ValueError(f"Invalid step ID: {step_id}")

        step = self.current_deployment.steps[step_id]
        if step.status not in (StepStatus.FAILED, StepStatus.PENDING):
            raise RuntimeError(
                f"Can only skip failed or pending steps, not {step.status.value}"
            )

        step.status = StepStatus.SKIPPED
        step.completed_at = datetime.utcnow()
        await self.log(step_id, "warn", f"Step '{step.description}' skipped by user")
        self._save_state()

        # Resume from the next step
        await self.resume_deployment(from_step=step_id + 1)
        return True

    async def cleanup(self) -> bool:
        """Run cleanup with Talos reset, Terraform destroy, and Ceph RBD cleanup.

        This method performs a complete cleanup by:
        1. Resetting all Talos nodes to wipe ephemeral partitions (CNI IPAM state)
        2. Running Terraform destroy to remove all infrastructure
        3. Purging orphaned CSI RBD volumes from the Ceph kubernetes pool
        4. Destroying Build VM (if deployed)
        5. Cleaning up SSH known_hosts entries

        The Talos reset prevents stale CNI/IPAM state from causing IP exhaustion
        on subsequent deployments. The Ceph cleanup removes RBD images that were
        provisioned by the CSI driver but can no longer be cleaned up by K8s
        finalizers after the cluster VMs are destroyed.
        """
        self._cleanup_running = True
        try:
            return await self._run_cleanup()
        finally:
            self._cleanup_running = False

    async def _run_cleanup(self) -> bool:
        """Internal cleanup implementation."""
        await self.log(-1, "info", "Starting cleanup process...")
        self.credentials = {}
        self.current_deployment = None
        self._clear_state()

        # Step 1: Reset Talos nodes to wipe ephemeral state (prevents IPAM exhaustion)
        await self.log(-1, "info", "Step 1: Resetting Talos nodes to wipe ephemeral state...")

        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        # Try to reset each node - continue even if some fail (VMs might already be down)
        reset_count = 0
        for node_ip in self.node_ips:
            await self.log(-1, "info", f"  Attempting to reset node {node_ip}...")

            # First check if the node is reachable
            check_result = await self.process_manager.run_command_simple(
                ["talosctl", "version", "--insecure", "-n", node_ip, "-e", node_ip],
                timeout=5
            )

            if not check_result.success and "Server:" not in (check_result.output or ""):
                await self.log(-1, "info", f"    Node {node_ip} not reachable (may already be down)")
                continue

            # Reset the node - wipe ephemeral partition, no reboot (we're destroying anyway)
            reset_result = await self.process_manager.run_command_simple(
                ["talosctl", "reset",
                 "--graceful=false",
                 "--reboot=false",
                 "--system-labels-to-wipe=EPHEMERAL",
                 "-n", node_ip, "-e", node_ip],
                env=env,
                timeout=60
            )

            if reset_result.success:
                await self.log(-1, "info", f"    Node {node_ip}: Reset successful (ephemeral wiped)")
                reset_count += 1
            else:
                # Log but continue - the node might be in maintenance mode or already reset
                error_preview = (reset_result.output or "unknown error")[:100]
                await self.log(-1, "warn", f"    Node {node_ip}: Reset failed ({error_preview})")

        await self.log(-1, "info", f"  Reset complete: {reset_count}/{len(self.node_ips)} nodes wiped")

        # Brief pause to allow reset operations to complete
        await asyncio.sleep(5)

        # Step 2: Terraform destroy
        await self.log(-1, "info", "Step 2: Running Terraform destroy...")

        result = await self.process_manager.run_command(
            ["terraform", "destroy", "-auto-approve"],
            cwd=self.terraform_dir,
            on_output=lambda line: self.log(-1, "info", line)
        )

        if result.success:
            await self.log(-1, "info", "Cluster Terraform destroy completed")
        else:
            await self.log(-1, "error", "Cluster Terraform destroy failed")

        # Step 3: Clean up orphaned Ceph RBD images from the kubernetes pool
        # When K8s VMs are destroyed, CSI-provisioned RBD volumes become orphaned
        # because the K8s PV finalizers can no longer run. Clean them up via SSH
        # to a Proxmox node which has direct access to the Ceph cluster.
        await self.log(-1, "info", "Step 3: Cleaning up orphaned Ceph RBD volumes...")
        proxmox_creds = self._read_proxmox_credentials()
        proxmox_ssh_pw = proxmox_creds.get("proxmox_ssh_password", "")
        settings = get_settings()

        if proxmox_ssh_pw:
            ceph_cleanup_cmd = (
                "rbd ls -p kubernetes 2>/dev/null | grep '^csi-vol-' | "
                "while read img; do "
                "rbd snap purge kubernetes/$img 2>/dev/null; "
                "rbd rm kubernetes/$img 2>/dev/null && "
                "echo \"Removed: $img\"; "
                "done; "
                "echo \"CSI volume cleanup complete\""
            )
            ceph_result = await self.process_manager.run_command(
                ["sshpass", "-p", proxmox_ssh_pw,
                 "ssh", "-o", "StrictHostKeyChecking=no",
                 f"{settings.proxmox_ssh_user}@{settings.proxmox_host}",
                 ceph_cleanup_cmd],
                on_output=lambda line: self.log(-1, "info", line),
                timeout=600,  # 10 minutes — may have hundreds of images
            )
            if ceph_result.success:
                await self.log(-1, "info", "Ceph RBD cleanup completed")
            else:
                await self.log(-1, "warn", "Ceph RBD cleanup failed (non-fatal) — orphaned volumes may remain")
        else:
            await self.log(-1, "warn", "Skipping Ceph cleanup — no Proxmox SSH password available")

        # Step 4: Destroy Build VM (if it was deployed)
        build_lxc_dir = self.repo_root / "terraform" / "build-lxc"
        build_tfvars = build_lxc_dir / "terraform.tfvars"
        if build_tfvars.exists():
            await self.log(-1, "info", "Step 4: Destroying Build VM...")
            build_result = await self.process_manager.run_command(
                ["terraform", "destroy", "-auto-approve"],
                cwd=build_lxc_dir,
                on_output=lambda line: self.log(-1, "info", line),
            )
            if build_result.success:
                await self.log(-1, "info", "Build VM destroyed")
                # Clean up generated tfvars
                try:
                    build_tfvars.unlink()
                except OSError:
                    pass
            else:
                await self.log(-1, "warn", "Build VM destroy failed (non-fatal)")

        # Step 5: Destroy target lab VMs (Metasploitable3 targets, VMID 5000-5099)
        await self.log(-1, "info", "Step 5: Destroying target lab VMs...")
        try:
            proxmox_creds = self._read_proxmox_credentials()
            px_url = proxmox_creds.get("proxmox_api_url", "")
            px_token = proxmox_creds.get("proxmox_api_token", "")
            if px_url and px_token:
                import httpx
                headers = {"Authorization": f"PVEAPIToken={px_token}"}
                base = px_url.rstrip("/") + "/api2/json"
                async with httpx.AsyncClient(verify=False, timeout=30.0, headers=headers) as client:
                    # Get online nodes
                    nodes_resp = await client.get(f"{base}/nodes")
                    nodes = [n["node"] for n in nodes_resp.json().get("data", [])
                             if isinstance(n, dict) and n.get("status") == "online"]
                    for node in nodes:
                        # List VMs on this node
                        vms_resp = await client.get(f"{base}/nodes/{node}/qemu")
                        for vm in vms_resp.json().get("data", []):
                            vmid = vm.get("vmid", 0)
                            if 5000 <= vmid < 5100:
                                await self.log(-1, "info", f"  Destroying target VM {vmid} on {node}")
                                try:
                                    await client.post(f"{base}/nodes/{node}/qemu/{vmid}/status/stop",
                                                      data={"forceStop": 1})
                                    import asyncio
                                    await asyncio.sleep(3)
                                    await client.delete(
                                        f"{base}/nodes/{node}/qemu/{vmid}",
                                        params={"destroy-unreferenced-disks": 1, "purge": 1},
                                    )
                                except Exception as e:
                                    await self.log(-1, "warn", f"  Failed to destroy VM {vmid}: {e}")
            else:
                await self.log(-1, "info", "  Skipped (no Proxmox credentials)")
        except Exception as e:
            await self.log(-1, "warn", f"  Target lab cleanup failed: {e}")

        # Step 6: Clean up stale SSH known_hosts entries
        await self.log(-1, "info", "Step 6: Cleaning up SSH known_hosts...")
        known_hosts_files = [
            Path.home() / ".ssh" / "known_hosts",
            Path("/root/.ssh/known_hosts"),
        ]
        cleanup_ips = list(self.node_ips) + [get_settings().build_vm_ip.split("/")[0]]
        for kh_path in known_hosts_files:
            if kh_path.exists():
                for ip in cleanup_ips:
                    await self.process_manager.run_command_simple(
                        ["ssh-keygen", "-f", str(kh_path), "-R", ip],
                        timeout=5,
                    )
                await self.log(-1, "info", f"  Cleaned {kh_path}")

        await self.log(-1, "info", "Cleanup completed")
        return result.success

    def _get_step_methods(self):
        """Return the ordered list of (step_id, method) tuples.

        Centralised so both ``_run_deployment`` and future steps can extend
        the list without duplicating it.
        """
        return [
            (0, self._step_validate_git),
            (1, self._step_check_dependencies),
            (2, self._step_terraform_deploy),
            (3, self._step_wait_for_vms),
            (4, self._step_generate_talos_config),
            (5, self._step_apply_talos_configs),
            (6, self._step_verify_cluster_health),
            (7, self._step_get_kubeconfig),
            (8, self._step_install_argocd),
            (9, self._step_deploy_infrastructure),
            (10, self._step_argocd_self_management),
            (11, self._step_deploy_openvas),
            (12, self._step_deploy_faraday),
            (13, self._step_deploy_metasploit),
            (14, self._step_deploy_threat_dragon),
            (15, self._step_deploy_harbor),
            (16, self._step_configure_integrations),
            (17, self._step_generate_secrets),
            (18, self._step_commit_push_secrets),
            (19, self._step_deploy_build_vm),
            (20, self._step_prepare_target_templates),
            (21, self._step_build_push_images),
            (22, self._step_deploy_cleanroom_apps),
            (23, self._step_apply_network_policies),
        ]

    async def _run_deployment(self, resume_from_step: int = 0):
        """Execute the deployment process, optionally resuming from a step.

        Args:
            resume_from_step: Step ID to resume from. Steps before this
                that are already SUCCESS or SKIPPED are left untouched.
        """
        try:
            steps = self._get_step_methods()

            for step_id, step_func in steps:
                if self.current_deployment.status != DeploymentStatus.RUNNING:
                    break

                # Skip completed/skipped steps when resuming
                if step_id < resume_from_step:
                    existing = self.current_deployment.steps[step_id]
                    if existing.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                        continue

                self.current_deployment.current_step = step_id
                await self.update_step(step_id, StepStatus.RUNNING)

                success = await step_func(step_id)

                if not success:
                    await self.update_step(step_id, StepStatus.FAILED)
                    self.current_deployment.status = DeploymentStatus.FAILED
                    step_desc = self.current_deployment.steps[step_id].description
                    self.current_deployment.error_message = f"Failed at step: {step_desc}"
                    await self.log(step_id, "error", f"Step failed: {step_desc}")
                    self._save_state()  # Checkpoint on failure
                    break

                await self.update_step(step_id, StepStatus.SUCCESS)
                self._save_state()  # Checkpoint after every successful step

            if self.current_deployment.status == DeploymentStatus.RUNNING:
                self.current_deployment.status = DeploymentStatus.COMPLETED
                await self.log(-1, "info", "Deployment completed successfully!")

        except Exception as e:
            self.current_deployment.status = DeploymentStatus.FAILED
            self.current_deployment.error_message = str(e)
            await self.log(-1, "error", f"Deployment failed with error: {e}")

        finally:
            self.current_deployment.completed_at = datetime.utcnow()
            self._save_state()

    async def _step_validate_git(self, step_id: int) -> bool:
        """Step 0: Validate git repository and configured paths.

        Verifies that:
        - REPO_ROOT exists and is accessible
        - The directory is a valid git repository
        - Required subdirectories (terraform, talos) are present

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if validation passes, False otherwise.
        """
        await self.log(step_id, "info", "Validating git repository...")

        # Log configured paths for debugging
        await self.log(step_id, "info", f"REPO_ROOT configured as: {self.repo_root}")
        await self.log(step_id, "info", f"Terraform directory: {self.terraform_dir}")
        await self.log(step_id, "info", f"Talos directory: {self.talos_dir}")

        if not self.repo_root.exists():
            await self.log(step_id, "error", f"Repository root not found: {self.repo_root}")
            return False

        result = await self.process_manager.run_command_simple(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.repo_root
        )

        if result.success:
            await self.log(step_id, "info", f"Repository root: {result.output.strip()}")
            return True
        else:
            await self.log(step_id, "error", "Not a valid git repository")
            return False

    async def _step_check_dependencies(self, step_id: int) -> bool:
        """Step 1: Check that all required CLI tools are available.

        Verifies the presence of: terraform, talhelper, talosctl, kubectl,
        helm, sops, jq, curl, yq, age.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if all dependencies are found, False if any are missing.
        """
        await self.log(step_id, "info", "Checking dependencies...")

        all_found = True
        for dep in self.dependencies:
            path = shutil.which(dep)
            if path:
                await self.log(step_id, "info", f"  {dep}: {path}")
            else:
                await self.log(step_id, "error", f"  {dep}: NOT FOUND")
                all_found = False

        return all_found

    async def _step_terraform_deploy(self, step_id: int) -> bool:
        """Step 2: Provision VMs on Proxmox using Terraform.

        Executes terraform init, plan, and apply to create the cluster VMs.
        Uses cluster.auto.tfvars and credentials.auto.tfvars for configuration.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if Terraform succeeds, False otherwise.
        """
        await self.log(step_id, "info", "Running terraform init...")

        result = await self.process_manager.run_command(
            ["terraform", "init"],
            cwd=self.terraform_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )
        if not result.success:
            return False

        await self.log(step_id, "info", "Running terraform plan...")
        result = await self.process_manager.run_command(
            ["terraform", "plan", "-out=.tfplan"],
            cwd=self.terraform_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )
        if not result.success:
            return False

        await self.log(step_id, "info", "Running terraform apply...")
        result = await self.process_manager.run_command(
            ["terraform", "apply", ".tfplan"],
            cwd=self.terraform_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_wait_for_vms(self, step_id: int) -> bool:
        """Step 3: Wait for VMs to boot and Talos API to be ready.

        Note: VMs boot with DHCP IPs initially. We need to query Proxmox guest agent
        to get the actual DHCP IP, then check Talos API on that IP.
        The FQDN won't work yet because it points to the static IP which isn't assigned
        until after configs are applied.
        """
        # Initial delay to allow VMs to fully boot before polling
        await self.log(step_id, "info", f"Waiting {VM_BOOT_INITIAL_DELAY}s for VMs to boot before checking Talos API...")

        # Wait in increments so we can check for cancellation
        for i in range(0, VM_BOOT_INITIAL_DELAY, BOOT_DELAY_CHECK_INTERVAL):
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False
            remaining = VM_BOOT_INITIAL_DELAY - i
            await self.log(step_id, "info", f"  Boot delay: {remaining}s remaining...")
            await asyncio.sleep(min(BOOT_DELAY_CHECK_INTERVAL, remaining))

        await self.log(step_id, "info", "Boot delay complete. Checking Talos API availability...")
        await self.log(step_id, "info", "Note: VMs are at DHCP IPs until config is applied")

        # Get VM details from terraform output
        result = await self.process_manager.run_command_simple(
            ["terraform", "output", "-json"],
            cwd=self.terraform_dir
        )

        if not result.success:
            await self.log(step_id, "error", "Failed to get terraform output")
            return False

        try:
            tf_output = json.loads(result.output)
            vm_details = tf_output.get("vm_details", {}).get("value", {})
        except json.JSONDecodeError:
            await self.log(step_id, "error", "Failed to parse terraform output")
            return False

        if not vm_details:
            await self.log(step_id, "warn", "No VM details found in terraform output")
            return True

        # Load Proxmox credentials for querying guest agent
        credentials_file = self.terraform_dir / "credentials.auto.tfvars"
        proxmox_endpoint = ""
        proxmox_token = ""

        if credentials_file.exists():
            try:
                content = credentials_file.read_text()
                endpoint_match = re.search(r'proxmox_api_url\s*=\s*"([^"]*)"', content)
                token_match = re.search(r'proxmox_api_token\s*=\s*"([^"]*)"', content)
                if endpoint_match:
                    proxmox_endpoint = endpoint_match.group(1).rstrip('/api2/json')
                if token_match:
                    proxmox_token = token_match.group(1)
            except Exception as e:
                await self.log(step_id, "warn", f"Could not read Proxmox credentials: {e}")

        # Wait for each VM's Talos API to be ready
        max_wait = VM_READY_MAX_ATTEMPTS * VM_READY_RETRY_INTERVAL

        await self.log(step_id, "info", f"Checking Talos API readiness (max wait: {max_wait}s per VM)...")

        for vm_name, details in vm_details.items():
            vmid = details.get("vmid")
            proxmox_node = details.get("proxmox_node", "")
            fqdn = details.get("fqdn", vm_name)

            await self.log(step_id, "info", f"Waiting for {vm_name} (VMID: {vmid})...")

            # Poll for DHCP IP from Proxmox guest agent, then check Talos API
            ready = False
            dhcp_ip = None

            for attempt in range(1, VM_READY_MAX_ATTEMPTS + 1):
                if self.current_deployment.status != DeploymentStatus.RUNNING:
                    return False

                # Try to get DHCP IP from Proxmox guest agent if we have credentials
                # Keep retrying until we get an IP (guest agent may not be ready yet)
                if proxmox_endpoint and proxmox_token and proxmox_node:
                    try:
                        curl_result = subprocess.run(
                            ["curl", "-s", "-k", "-H", f"Authorization: PVEAPIToken={proxmox_token}",
                             f"{proxmox_endpoint}/api2/json/nodes/{proxmox_node}/qemu/{vmid}/agent/network-get-interfaces"],
                            capture_output=True, text=True, timeout=PROXMOX_API_TIMEOUT
                        )
                        if curl_result.returncode == 0:
                            agent_data = json.loads(curl_result.stdout)
                            if "data" in agent_data and "result" in agent_data["data"]:
                                for iface in agent_data["data"]["result"]:
                                    if iface.get("name") != "lo":
                                        for ip_info in iface.get("ip-addresses", []):
                                            if ip_info.get("ip-address-type") == "ipv4":
                                                new_ip = ip_info.get("ip-address")
                                                if new_ip and new_ip != dhcp_ip:
                                                    dhcp_ip = new_ip
                                                    await self.log(step_id, "info", f"  Found DHCP IP: {dhcp_ip}")
                                                break
                                    if dhcp_ip:
                                        break
                            elif "data" in agent_data and agent_data["data"] is None:
                                await self.log(step_id, "info", f"  Guest agent not ready yet...")
                            elif "errors" in agent_data:
                                await self.log(step_id, "info", f"  Guest agent error: {agent_data.get('errors', {})}")
                        else:
                            await self.log(step_id, "info", f"  Curl failed: {curl_result.stderr}")
                    except json.JSONDecodeError as e:
                        await self.log(step_id, "info", f"  Guest agent response not JSON: {curl_result.stdout[:100] if curl_result else 'N/A'}")
                    except Exception as e:
                        await self.log(step_id, "info", f"  Guest agent query failed: {e}")
                else:
                    if not proxmox_endpoint:
                        await self.log(step_id, "warn", "  No Proxmox endpoint configured")
                    if not proxmox_token:
                        await self.log(step_id, "warn", "  No Proxmox token configured")
                    if not proxmox_node:
                        await self.log(step_id, "warn", f"  No Proxmox node for VM {vm_name}")

                # If we have a DHCP IP, check Talos API on that IP
                if dhcp_ip:
                    # Use 'talosctl version --insecure' which works in maintenance mode
                    # Note: In talosctl 1.12+, --insecure is only supported for version and apply-config
                    check_result = await self.process_manager.run_command_simple(
                        ["talosctl", "version", "--insecure", "-n", dhcp_ip, "-e", dhcp_ip],
                        timeout=TALOS_API_CHECK_TIMEOUT
                    )

                    # Log the actual response for debugging
                    output_preview = (check_result.output or "")[:200].replace('\n', ' ')
                    await self.log(step_id, "info", f"  talosctl version response (rc={check_result.return_code}): {output_preview}")

                    # The API is ready if:
                    # 1. Command succeeds (exit code 0), OR
                    # 2. Output contains "Server:" indicating we got a response from Talos
                    # 3. Response contains "maintenance mode" (explicit maintenance indicator)
                    if check_result.success:
                        await self.log(step_id, "info", f"  {vm_name}: Talos API ready at {dhcp_ip}")
                        ready = True
                        break
                    elif check_result.output and "Server:" in check_result.output:
                        await self.log(step_id, "info", f"  {vm_name}: Talos API ready at {dhcp_ip} (got server version)")
                        ready = True
                        break
                    elif check_result.output and "maintenance mode" in check_result.output.lower():
                        await self.log(step_id, "info", f"  {vm_name}: Talos API ready at {dhcp_ip} (maintenance mode)")
                        ready = True
                        break
                    else:
                        await self.log(step_id, "info", f"  Talos API not responding at {dhcp_ip}")

                await self.log(step_id, "info", f"  Attempt {attempt}/{VM_READY_MAX_ATTEMPTS} - waiting {VM_READY_RETRY_INTERVAL}s...")
                await asyncio.sleep(VM_READY_RETRY_INTERVAL)

            if not ready:
                if not dhcp_ip:
                    await self.log(step_id, "error", f"  {vm_name}: Could not get DHCP IP from guest agent after {max_wait}s")
                else:
                    await self.log(step_id, "error", f"  {vm_name}: Talos API not ready at {dhcp_ip} after {max_wait}s")
                return False

        await self.log(step_id, "info", "All VMs are ready with Talos API available")
        return True

    async def _step_generate_talos_config(self, step_id: int) -> bool:
        """Step 4: Generate Talos configuration using talhelper.

        This step:
        1. Runs tfvars-to-talos-env.sh to convert Terraform vars to Talos format
        2. Cleans up old configuration files
        3. Generates Talos secrets with talhelper gensecret
        4. Encrypts secrets with SOPS
        5. Generates full Talos config with talhelper genconfig

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if configuration generation succeeds, False otherwise.
        """
        sops_key_file = os.environ.get(
            "SOPS_AGE_KEY_FILE",
            os.path.expanduser("~/.config/sops/age/keys.txt")
        )
        env = {"SOPS_AGE_KEY_FILE": sops_key_file}

        # Verify talos_dir exists (should contain talconfig.yaml, apply-configs.sh, etc.)
        if not self.talos_dir.exists():
            await self.log(step_id, "error", f"Talos directory not found: {self.talos_dir}")
            await self.log(step_id, "error", f"REPO_ROOT may be misconfigured. Current value: {self.repo_root}")
            await self.log(step_id, "error", "Check that REPO_ROOT in .env matches the actual repository path")
            return False

        # Verify talconfig.yaml exists (required for config generation)
        talconfig_file = self.talos_dir / "talconfig.yaml"
        if not talconfig_file.exists():
            await self.log(step_id, "error", f"talconfig.yaml not found in {self.talos_dir}")
            await self.log(step_id, "error", "This file is required for Talos config generation")
            return False

        await self.log(step_id, "info", f"Found talconfig.yaml in {self.talos_dir}")

        # Ensure clusterconfig directory exists
        clusterconfig_dir = self.talos_dir / "clusterconfig"
        if not clusterconfig_dir.exists():
            await self.log(step_id, "info", f"Creating clusterconfig directory: {clusterconfig_dir}")
            clusterconfig_dir.mkdir(parents=True, exist_ok=True)

        # Clean up any existing generated configs for a fresh start
        await self.log(step_id, "info", "Cleaning up old generated configs...")
        for config_file in clusterconfig_dir.glob("*.yaml"):
            try:
                config_file.unlink()
                await self.log(step_id, "info", f"  Removed: {config_file.name}")
            except Exception as e:
                await self.log(step_id, "warn", f"  Could not remove {config_file.name}: {e}")

        # Also remove old talosconfig if it exists
        talosconfig_file = clusterconfig_dir / "talosconfig"
        if talosconfig_file.exists():
            try:
                talosconfig_file.unlink()
                await self.log(step_id, "info", "  Removed: talosconfig")
            except Exception as e:
                await self.log(step_id, "warn", f"  Could not remove talosconfig: {e}")

        # Run tfvars-to-talos-env.sh
        await self.log(step_id, "info", "Running tfvars-to-talos-env.sh...")
        script_path = self.repo_root / "scripts" / "tfvars-to-talos-env.sh"

        result = await self.process_manager.run_command(
            ["bash", str(script_path), "--force"],
            cwd=self.repo_root,
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )
        if not result.success:
            await self.log(step_id, "error", f"tfvars-to-talos-env.sh failed: {result.output}")
            return False

        # Remove existing secret files to ensure fresh generation
        # talhelper genconfig checks: talsecret.yaml, talsecret.sops.yaml, talsecret.yml, talsecret.sops.yml
        for secret_filename in ["talsecret.yaml", "talsecret.sops.yaml", "talsecret.yml", "talsecret.sops.yml"]:
            old_secret = self.talos_dir / secret_filename
            if old_secret.exists():
                await self.log(step_id, "info", f"Removing existing {secret_filename} for fresh generation...")
                try:
                    old_secret.unlink()
                except Exception as e:
                    await self.log(step_id, "warn", f"Could not remove {secret_filename}: {e}")

        # Define the secret file path we'll write to
        secret_file = self.talos_dir / "talsecret.sops.yaml"

        # Generate Talos secret
        await self.log(step_id, "info", "Generating Talos secret...")

        result = await self.process_manager.run_command_simple(
            ["talhelper", "gensecret"],
            cwd=self.talos_dir,
            env=env
        )
        if not result.success:
            await self.log(step_id, "error", f"talhelper gensecret failed: {result.output}")
            return False

        # Write secret to file
        try:
            with open(secret_file, 'w') as f:
                f.write(result.output)
            await self.log(step_id, "info", f"Secret written to {secret_file}")
        except Exception as e:
            await self.log(step_id, "error", f"Failed to write secret file: {e}")
            return False

        # Encrypt with SOPS
        await self.log(step_id, "info", "Encrypting secret with SOPS...")
        result = await self.process_manager.run_command(
            ["sops", "-e", "-i", str(secret_file.name)],
            cwd=self.talos_dir,
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )
        if not result.success:
            await self.log(step_id, "error", f"SOPS encryption failed: {result.output}")
            return False

        # Generate Talos config
        await self.log(step_id, "info", "Generating Talos config with talhelper genconfig...")
        result = await self.process_manager.run_command(
            ["talhelper", "genconfig", "--env-file", "talenv.yaml"],
            cwd=self.talos_dir,
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        if not result.success:
            await self.log(step_id, "error", f"talhelper genconfig failed: {result.output}")
            return False

        # Verify configs were generated
        generated_configs = list(clusterconfig_dir.glob("*.yaml"))
        talosconfig_exists = (clusterconfig_dir / "talosconfig").exists()

        if not generated_configs:
            await self.log(step_id, "error", "No config files were generated in clusterconfig/")
            return False

        if not talosconfig_exists:
            await self.log(step_id, "error", "talosconfig was not generated")
            return False

        await self.log(step_id, "info", f"Generated {len(generated_configs)} config files and talosconfig")
        for cfg in generated_configs:
            await self.log(step_id, "info", f"  - {cfg.name}")

        return True

    async def _step_apply_talos_configs(self, step_id: int) -> bool:
        """Step 5: Apply Talos configurations to cluster nodes.

        Runs apply-configs.sh with --bootstrap flag to:
        1. Apply machine configs to each node
        2. Bootstrap the first control plane node
        3. Wait for etcd and Kubernetes to initialize

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if configs are applied successfully, False otherwise.
        """
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        await self.log(step_id, "info", "Running apply-configs.sh --bootstrap...")
        result = await self.process_manager.run_command(
            ["bash", "apply-configs.sh", "--bootstrap"],
            cwd=self.talos_dir,
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_verify_cluster_health(self, step_id: int) -> bool:
        """Step 6: Verify cluster health using talosctl health.

        Polls the cluster health endpoint until the cluster reports healthy
        or the maximum retry count is exceeded.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if cluster is healthy, False if health check times out.
        """
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        max_wait = self.health_check_retries * self.health_check_interval
        await self.log(step_id, "info", f"Waiting for cluster health (max wait: {max_wait}s)...")
        await self.log(step_id, "info", f"Using TALOSCONFIG: {talosconfig}")
        master = self._resolve_master_node()
        await self.log(step_id, "info", f"Target node: {master}")

        for i in range(1, self.health_check_retries + 1):
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            result = await self.process_manager.run_command_simple(
                ["talosctl", "health",
                 f"--nodes={master}",
                 f"--endpoints={master}"],
                env=env,
                timeout=60
            )

            if result.success:
                await self.log(step_id, "info", "Cluster is healthy!")
                return True

            # Log the actual error to help diagnose issues
            error_preview = (result.output or "no output")[:300].replace('\n', ' ')
            await self.log(step_id, "info", f"Health check failed (rc={result.return_code}): {error_preview}")
            await self.log(step_id, "info", f"Retrying ({i}/{self.health_check_retries})...")
            await asyncio.sleep(self.health_check_interval)

        await self.log(step_id, "error", "Cluster failed to become healthy")
        return False

    async def _step_get_kubeconfig(self, step_id: int) -> bool:
        """Step 7: Retrieve kubeconfig from the cluster.

        Gets the kubeconfig from the master node and saves it to ~/.kube/config
        for kubectl access.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if kubeconfig is retrieved, False otherwise.
        """
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}
        kubeconfig_path = Path.home() / ".kube" / "config"

        # Ensure .kube directory exists
        kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale kubeconfig so talosctl writes a clean file
        # (talosctl kubeconfig merges into existing files, accumulating
        # stale cluster/user entries from previous deployments)
        if kubeconfig_path.exists():
            kubeconfig_path.unlink()
            await self.log(step_id, "info", "Removed stale kubeconfig from previous deployment")

        await self.log(step_id, "info", f"Retrieving kubeconfig to {kubeconfig_path}...")
        result = await self.process_manager.run_command(
            ["talosctl", "kubeconfig", f"--nodes={self._resolve_master_node()}", str(kubeconfig_path)],
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        if not result.success:
            return False

        # Push kubeconfig to build VM (best-effort — build VM may not exist yet)
        build_vm_ip = "10.83.3.191"
        build_vm_user = "deploy"
        await self.log(step_id, "info", f"Pushing kubeconfig to build VM ({build_vm_ip})...")

        ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=5"
        push_result = await self.process_manager.run_command_simple(
            ["bash", "-c",
             f"scp {ssh_opts} {kubeconfig_path} {build_vm_user}@{build_vm_ip}:/tmp/kubeconfig && "
             f"ssh {ssh_opts} {build_vm_user}@{build_vm_ip} "
             f"'mkdir -p ~/.kube && mv /tmp/kubeconfig ~/.kube/config && chmod 600 ~/.kube/config && "
             f"sudo cp ~/.kube/config /root/.kube/config && sudo chmod 600 /root/.kube/config'"],
            timeout=15
        )

        if push_result.success:
            await self.log(step_id, "info", "Kubeconfig pushed to build VM successfully")
        else:
            await self.log(step_id, "warn", "Build VM not reachable — kubeconfig not pushed (deploy build VM later)")

        return True

    async def _step_install_argocd(self, step_id: int) -> bool:
        """Step 8: Install ArgoCD GitOps platform.

        Runs the ArgoCD install script which installs ArgoCD via Helm
        with custom values including admin credentials.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if ArgoCD installs successfully, False otherwise.
        """
        await self.log(step_id, "info", "Running ArgoCD install script...")

        result = await self.process_manager.run_command(
            ["bash", "install.sh"],
            cwd=self.argocd_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        if result.success:
            self.credentials["argocd"] = {
                "username": "admin", "password": "admin",
                "note": "Default - change via ArgoCD CLI"
            }
            self._save_state()

        return result.success

    async def _step_deploy_infrastructure(self, step_id: int) -> bool:
        """Step 9: Deploy infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI).

        Runs deploy-ingress-stack.sh which deploys and configures:
        - MetalLB for load balancer IPs
        - cert-manager for TLS certificates
        - Traefik as ingress controller
        - Ceph CSI RBD for persistent storage (direct Ceph RBD from Proxmox cluster)

        Also creates the basic-auth-secret for Traefik middleware.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if infrastructure deploys successfully, False otherwise.
        """
        await self.log(step_id, "info", "Running deploy-ingress-stack.sh...")

        result = await self.process_manager.run_command(
            ["bash", "deploy-ingress-stack.sh"],
            cwd=self.projects_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        if not result.success:
            return False

        # Create basic-auth-secret for Traefik middleware
        # This secret is used for protecting dashboards (Traefik)
        # Default credentials: admin / admin (change in production)
        await self.log(step_id, "info", "Creating Traefik basic-auth-secret...")
        auth_result = await self._create_secret(
            step_id,
            namespace="traefik",
            secret_name="basic-auth-secret",
            # htpasswd bcrypt hash for admin:admin (generated with htpasswd -nbB)
            data={"users": "admin:$2y$05$ol3jkw2coZieHvhoho3k8uEFlDWcCzOvtZvxPu9MVv1.mpAp8x3Uu"}
        )

        if not auth_result:
            await self.log(step_id, "warn", "Could not create basic-auth-secret, continuing...")

        self.credentials["traefik"] = {
            "username": "admin", "password": "admin",
            "note": "Also protects Threat Dragon"
        }
        self._save_state()

        return True

    async def _step_argocd_self_management(self, step_id: int) -> bool:
        """Step 10: Enable ArgoCD self-management via GitOps.

        Applies the ArgoCD Application resource that makes ArgoCD manage itself,
        enabling GitOps-based updates to the ArgoCD configuration.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if self-management is enabled, False otherwise.
        """
        await self.log(step_id, "info", "Enabling ArgoCD self-management...")

        if not await self._deploy_argocd_app("argocd", step_id):
            return False

        await self.log(step_id, "info", "Waiting for ArgoCD self-management sync...")
        await asyncio.sleep(ARGOCD_SYNC_WAIT)
        return True

    async def _step_deploy_openvas(self, step_id: int) -> bool:
        """Step 11: Deploy OpenVAS vulnerability scanner.

        Creates required secrets and deploys the Greenbone OpenVAS stack
        via ArgoCD Application. OpenVAS provides vulnerability scanning
        capabilities.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if deployment initiated, False otherwise.
        """
        await self.log(step_id, "info", "Deploying OpenVAS...")

        # Create namespace if it doesn't exist (ignore error if already exists)
        await self.k8s.ensure_namespace("openvas")

        # Create required secret
        await self.log(step_id, "info", "Creating OpenVAS credentials secret...")
        openvas_admin_password = self._generate_password()
        secret_created = await self._create_secret(
            step_id,
            namespace="openvas",
            secret_name="openvas-credentials",
            data={
                "admin-password": openvas_admin_password,
                "postgres-password": self._generate_password()
            }
        )
        self.credentials["openvas"] = {
            "username": "admin", "password": openvas_admin_password
        }
        self._save_state()

        if not secret_created:
            await self.log(step_id, "warn", "Could not create secret, continuing anyway...")

        if not await self._deploy_argocd_app("openvas", step_id):
            return False
        if not await self._wait_for_argocd_sync("openvas", step_id):
            return False

        # Wait for PVCs to bind (OpenVAS needs 10 PVCs from Ceph CSI)
        await self.log(step_id, "info", "Checking OpenVAS PVC binding (10 PVCs)...")
        for i in range(18):  # up to 3 minutes
            pvc_result = await self.process_manager.run_command(
                ["kubectl", "get", "pvc", "-n", "openvas", "--no-headers"],
                timeout=15
            )
            pvc_output = (pvc_result.output or "").strip()
            if not pvc_output:
                await self.log(step_id, "info", f"Waiting for PVCs to appear... ({i+1}/18)")
                await asyncio.sleep(10)
                continue

            pvc_lines = pvc_output.split('\n')
            bound = sum(1 for l in pvc_lines if 'Bound' in l)
            total = len(pvc_lines)
            if bound == total and total > 0:
                await self.log(step_id, "info", f"All {bound}/{total} PVCs bound")
                break
            pending_pvcs = [l.split()[0] for l in pvc_lines if 'Pending' in l]
            await self.log(step_id, "info",
                f"PVCs: {bound}/{total} bound, pending: {', '.join(pending_pvcs[:3])}... ({i+1}/18)")
            await asyncio.sleep(10)

        # Wait for OpenVAS pod to be scheduled and init containers to start
        await self.log(step_id, "info", "Waiting for OpenVAS pod to initialize...")
        pod_progressing = False
        for i in range(24):  # up to 4 minutes
            # Get pod status in detail
            status_result = await self.process_manager.run_command(
                ["kubectl", "get", "pods", "-n", "openvas", "-l", "app.kubernetes.io/name=greenbone",
                 "-o", "jsonpath={.items[0].status.phase}|{.items[0].status.initContainerStatuses[*].name}|"
                 "{.items[0].status.initContainerStatuses[*].ready}|"
                 "{.items[0].status.containerStatuses[*].ready}"],
                timeout=15
            )
            raw = (status_result.output or "").strip()
            parts = raw.split('|')
            phase = parts[0] if len(parts) > 0 else ""
            init_names = parts[1].split() if len(parts) > 1 and parts[1] else []
            init_ready = parts[2].split() if len(parts) > 2 and parts[2] else []
            container_ready = parts[3].split() if len(parts) > 3 and parts[3] else []

            if phase == "Running":
                ready_count = sum(1 for r in container_ready if r == "true")
                await self.log(step_id, "info",
                    f"OpenVAS pod running ({ready_count}/{len(container_ready)} containers ready)")
                pod_progressing = True
                break

            if init_names:
                # Init containers exist — show progress
                done = sum(1 for r in init_ready if r == "true")
                total_init = len(init_names)
                current = init_names[done] if done < total_init else "done"
                await self.log(step_id, "info",
                    f"Init containers: {done}/{total_init} complete (running: {current})... ({i+1}/24)")
                pod_progressing = True
            elif phase == "Pending":
                await self.log(step_id, "info", f"Pod pending (scheduling)... ({i+1}/24)")
            elif not phase:
                await self.log(step_id, "info", f"Waiting for pod... ({i+1}/24)")
            else:
                await self.log(step_id, "info", f"Pod phase: {phase}... ({i+1}/24)")
            await asyncio.sleep(10)

        if not pod_progressing:
            # Dump diagnostics for stuck pod
            await self.log(step_id, "warn", "OpenVAS pod not progressing — collecting diagnostics...")
            events = await self.process_manager.run_command(
                ["kubectl", "get", "events", "-n", "openvas", "--sort-by=.lastTimestamp",
                 "--field-selector", "type!=Normal"],
                timeout=15
            )
            if events.output and events.output.strip():
                for line in events.output.strip().split('\n')[-10:]:
                    await self.log(step_id, "warn", line)
            desc = await self.process_manager.run_command(
                ["kubectl", "describe", "pod", "-n", "openvas",
                 "-l", "app.kubernetes.io/name=greenbone"],
                timeout=15
            )
            if desc.output:
                # Show Events section from describe
                in_events = False
                for line in desc.output.split('\n'):
                    if 'Events:' in line:
                        in_events = True
                    if in_events:
                        await self.log(step_id, "info", line)
        else:
            await self.log(step_id, "info",
                "OpenVAS initializing (11 init containers + 6 services). "
                "Full startup takes 15-30 min — this is normal. Continuing deployment.")

        return True

    async def _step_deploy_faraday(self, step_id: int) -> bool:
        """Step 12: Deploy Faraday vulnerability management platform.

        Creates required secrets, deploys Faraday via ArgoCD Application,
        and creates the initial admin user. Faraday aggregates vulnerability
        data from multiple sources including OpenVAS and Metasploit.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if deployment initiated, False otherwise.
        """
        await self.log(step_id, "info", "Deploying Faraday...")

        # Create namespace if it doesn't exist (ignore error if already exists)
        await self.k8s.ensure_namespace("faraday")

        # Generate and store admin password for user creation
        admin_password = self._generate_password()

        # Create required secret
        await self.log(step_id, "info", "Creating Faraday credentials secret...")
        secret_created = await self._create_secret(
            step_id,
            namespace="faraday",
            secret_name="faraday-credentials",
            data={
                "postgres-password": self._generate_password(),
                "admin-password": admin_password
            }
        )

        if not secret_created:
            await self.log(step_id, "warn", "Could not create secret, continuing anyway...")

        self.credentials["faraday"] = {
            "username": "admin", "password": admin_password
        }
        self._save_state()

        if not await self._deploy_argocd_app("faraday", step_id):
            return False

        # Wait for Faraday deployment to be ready before creating user
        await self.log(step_id, "info", "Waiting for Faraday deployment to be ready...")
        for attempt in range(1, 31):  # Max 5 minutes (30 * 10s)
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            ready_result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "deployment", "faraday", "-n", "faraday",
                 "-o", "jsonpath={.status.readyReplicas}"],
                timeout=30
            )

            if ready_result.success and ready_result.output.strip() == "1":
                await self.log(step_id, "info", "Faraday deployment is ready")
                break

            await self.log(step_id, "info", f"Waiting for Faraday pod... ({attempt}/30)")
            await asyncio.sleep(10)
        else:
            await self.log(step_id, "warn", "Faraday not ready after 5 minutes, skipping user creation")
            return True

        # Create initial admin user
        await self.log(step_id, "info", "Creating Faraday admin user...")
        user_result = await self.process_manager.run_command(
            ["kubectl", "exec", "-n", "faraday", "deployment/faraday", "-c", "faraday",
             "--", "faraday-manage", "create-superuser",
             "--username", "admin",
             "--email", "admin@knowledgeondemand.net",
             "--password", admin_password],
            on_output=lambda line: self.log(step_id, "info", line),
            timeout=60
        )

        if user_result.success:
            await self.log(step_id, "info", "Faraday admin user created successfully")
        else:
            await self.log(step_id, "warn", f"Could not create Faraday admin user: {user_result.output}")

        return True

    async def _step_deploy_metasploit(self, step_id: int) -> bool:
        """Step 13: Deploy Metasploit penetration testing framework.

        Creates required secrets and deploys Metasploit via ArgoCD Application.
        Metasploit provides exploit development and penetration testing
        capabilities.

        Args:
            step_id: The deployment step identifier for logging.

        Returns:
            True if deployment initiated, False otherwise.
        """
        await self.log(step_id, "info", "Deploying Metasploit...")

        # Create namespace if it doesn't exist (ignore error if already exists)
        await self.k8s.ensure_namespace("metasploit")

        # Create required secrets
        await self.log(step_id, "info", "Creating Metasploit credentials secrets...")
        msf_db_password = self._generate_password()
        msf_rpc_password = self._generate_password()

        db_secret_created = await self._create_secret(
            step_id,
            namespace="metasploit",
            secret_name="metasploit-db-credentials",
            data={"password": msf_db_password}
        )

        rpc_secret_created = await self._create_secret(
            step_id,
            namespace="metasploit",
            secret_name="metasploit-rpc-credentials",
            data={"password": msf_rpc_password}
        )

        if not (db_secret_created and rpc_secret_created):
            await self.log(step_id, "warn", "Could not create all secrets, continuing anyway...")

        self.credentials["metasploit_db"] = {
            "username": "msf", "password": msf_db_password,
            "note": "Database"
        }
        self.credentials["metasploit_rpc"] = {
            "username": "admin", "password": msf_rpc_password,
            "note": "RPC access"
        }
        self._save_state()

        return await self._deploy_argocd_app("metasploit", step_id)

    async def _step_deploy_threat_dragon(self, step_id: int) -> bool:
        """Step 14: Deploy Threat Dragon via ArgoCD Application."""
        await self.log(step_id, "info", "Deploying Threat Dragon...")

        if not await self._deploy_argocd_app("threat-dragon", step_id):
            return False
        return await self._wait_for_argocd_sync("threat-dragon", step_id)

    async def _step_deploy_harbor(self, step_id: int) -> bool:
        """Step 15: Deploy Harbor container registry via ArgoCD Application."""
        await self.log(step_id, "info", "Deploying Harbor container registry...")

        if not await self._deploy_argocd_app("harbor", step_id):
            return False
        if not await self._wait_for_argocd_sync("harbor", step_id):
            return False

        # Log deployment summary
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "==========================================")
        await self.log(step_id, "info", "All applications deployed!")
        await self.log(step_id, "info", "==========================================")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Credentials:")
        await self.log(step_id, "info", "  - ArgoCD:     admin / (use 'argocd admin initial-password -n argocd')")
        await self.log(step_id, "info", "  - OpenVAS:    admin / (auto-generated)")
        await self.log(step_id, "info", "  - Faraday:    admin / (auto-generated, user auto-created)")
        await self.log(step_id, "info", "  - Metasploit: msf / (auto-generated)")
        await self.log(step_id, "info", "  - Harbor:     admin / Harbor12345 (change on first login)")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Retrieve auto-generated passwords:")
        await self.log(step_id, "info", "  OpenVAS:    kubectl get secret openvas-credentials -n openvas -o jsonpath='{.data.admin-password}' | base64 -d")
        await self.log(step_id, "info", "  Faraday:    kubectl get secret faraday-credentials -n faraday -o jsonpath='{.data.admin-password}' | base64 -d")
        await self.log(step_id, "info", "  Metasploit: kubectl get secret metasploit-db-credentials -n metasploit -o jsonpath='{.data.password}' | base64 -d")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Access services at:")
        await self.log(step_id, "info", "  - ArgoCD:        https://argocd.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Traefik:       https://traefik.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Harbor:        https://harbor.knowledgeondemand.net")
        await self.log(step_id, "info", "  - OpenVAS:       https://openvas.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Faraday:       https://faraday.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Threat Dragon: https://threatdragon.knowledgeondemand.net")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Metasploit access (CLI only - no web UI):")
        await self.log(step_id, "info", "  kubectl exec -it -n metasploit deployment/metasploit -c metasploit -- ./msfconsole")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Note: OpenVAS feed sync takes 30-60 minutes on first deployment.")
        await self.log(step_id, "info", "Note: Build and push the LOKI-RS image from the build VM for IOC scanning.")
        await self.log(step_id, "info", "==========================================")

        return True

    async def _step_configure_integrations(self, step_id: int) -> bool:
        """Step 16: Configure security tool integrations.

        Creates a default Faraday workspace and verifies cross-service
        connectivity between Faraday, Metasploit, and OpenVAS.

        This step is non-fatal — partial failures are logged as warnings
        and the deployment still completes successfully.
        """
        await self.log(step_id, "info", "Configuring security tool integrations...")

        faraday_creds = self.credentials.get("faraday", {})
        faraday_password = faraday_creds.get("password", "")
        faraday_username = faraday_creds.get("username", "admin")

        if not faraday_password:
            await self.log(step_id, "warn", "Faraday credentials not available, skipping integration config")
            return True

        # --- Sub-task 1: Wait for Faraday API readiness ---
        await self.log(step_id, "info", "Waiting for Faraday REST API to be responsive...")

        api_ready = False
        for attempt in range(1, 31):
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            check_result = await self.process_manager.run_command_simple(
                ["kubectl", "exec", "-n", "faraday", "deployment/faraday", "-c", "faraday",
                 "--", "python3", "-c",
                 "import urllib.request; "
                 "resp = urllib.request.urlopen('http://127.0.0.1:5985/_api/v3/info'); "
                 "print(resp.status)"],
                timeout=15
            )

            status_code = (check_result.output or "").strip()
            if status_code == "200":
                await self.log(step_id, "info", "Faraday API is responsive")
                api_ready = True
                break

            await self.log(step_id, "info", f"  Faraday API not ready yet... ({attempt}/30)")
            await asyncio.sleep(10)

        if not api_ready:
            await self.log(step_id, "warn", "Faraday API not responsive after 5 minutes, skipping integration config")
            return True

        # --- Sub-task 2: Login + Create workspace (single kubectl exec) ---
        await self.log(step_id, "info", "Creating default Faraday workspace 'pentest'...")

        # Python script that runs inside the Faraday container
        # Uses session-based auth (login → CSRF token → create workspace)
        setup_script = (
            "import urllib.request, json, http.cookiejar, os, sys\n"
            "cj = http.cookiejar.CookieJar()\n"
            "opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))\n"
            "try:\n"
            "    data = json.dumps({'email': os.environ['FARADAY_USER'], 'password': os.environ['FARADAY_PASS']}).encode()\n"
            "    req = urllib.request.Request('http://127.0.0.1:5985/_api/login', method='POST',\n"
            "        headers={'Content-Type': 'application/json'}, data=data)\n"
            "    resp = opener.open(req)\n"
            "    login = json.loads(resp.read().decode())\n"
            "    csrf = login['response']['csrf_token']\n"
            "    print('LOGIN:OK')\n"
            "except Exception as e:\n"
            "    print(f'LOGIN:FAILED:{e}')\n"
            "    sys.exit(0)\n"
            "try:\n"
            "    ws = json.dumps({'name': 'pentest', 'description': 'Default workspace for security assessments'}).encode()\n"
            "    req2 = urllib.request.Request('http://127.0.0.1:5985/_api/v3/ws', method='POST',\n"
            "        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, data=ws)\n"
            "    resp2 = opener.open(req2)\n"
            "    print('WORKSPACE:CREATED')\n"
            "except urllib.error.HTTPError as e:\n"
            "    if e.code == 409:\n"
            "        print('WORKSPACE:EXISTS')\n"
            "    else:\n"
            "        print(f'WORKSPACE:ERROR:{e.code}')\n"
            "except Exception as e:\n"
            "    print(f'WORKSPACE:FAILED:{e}')\n"
        )

        # Pass credentials via environment variables (not command-line args)
        setup_result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "faraday", "deployment/faraday", "-c", "faraday",
             "--", "env", f"FARADAY_USER={faraday_username}", f"FARADAY_PASS={faraday_password}",
             "python3", "-c", setup_script],
            timeout=30
        )

        output = (setup_result.output or "").strip()
        for line in output.split("\n"):
            line = line.strip()
            if line == "LOGIN:OK":
                await self.log(step_id, "info", "Faraday API authentication successful")
            elif line.startswith("LOGIN:FAILED"):
                await self.log(step_id, "warn", f"Faraday login failed: {line}")
            elif line == "WORKSPACE:CREATED":
                await self.log(step_id, "info", "Workspace 'pentest' created successfully")
            elif line == "WORKSPACE:EXISTS":
                await self.log(step_id, "info", "Workspace 'pentest' already exists")
            elif line.startswith("WORKSPACE:ERROR") or line.startswith("WORKSPACE:FAILED"):
                await self.log(step_id, "warn", f"Workspace creation issue: {line}")

        # --- Sub-task 3: Verify Metasploit RPC connectivity ---
        await self.log(step_id, "info", "Verifying Metasploit RPC connectivity from Faraday...")

        msf_check = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "faraday", "deployment/faraday", "-c", "faraday",
             "--", "python3", "-c",
             "import socket; s = socket.socket(); s.settimeout(5); "
             "s.connect(('metasploit.metasploit.svc.cluster.local', 55553)); "
             "s.close(); print('REACHABLE')"],
            timeout=15
        )

        msf_status = (msf_check.output or "").strip()
        if "REACHABLE" in msf_status:
            await self.log(step_id, "info", "Metasploit RPC is reachable from Faraday (port 55553)")
        else:
            await self.log(step_id, "warn",
                "Metasploit RPC not yet reachable from Faraday. "
                "This is normal if Metasploit is still initializing (~90s startup).")

        # --- Sub-task 4: Log integration summary ---
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "=== Integration Configuration Summary ===")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Faraday workspace 'pentest' is ready.")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Metasploit Integration:")
        await self.log(step_id, "info", "  Faraday imports Metasploit results via XML report upload.")
        await self.log(step_id, "info", "  1. In msfconsole: db_export -f xml /tmp/msf-report.xml")
        await self.log(step_id, "info", "  2. Upload to Faraday via Web UI (pentest workspace → upload icon)")
        await self.log(step_id, "info", "     or API: POST /_api/v3/ws/pentest/upload_report")
        await self.log(step_id, "info", f"  RPC endpoint: metasploit.metasploit.svc.cluster.local:55553")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "OpenVAS Integration:")
        await self.log(step_id, "info", "  Export scan reports as XML from the OpenVAS GSA web UI,")
        await self.log(step_id, "info", "  then upload to Faraday. Faraday auto-detects OpenVAS XML format.")
        await self.log(step_id, "info", "  Supported formats: OpenVAS XML, Nmap XML, Metasploit XML, and 80+ others.")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "=== Integration setup complete ===")

        return True

    # =================================================================
    # Part 2: New deployment steps (17-22)
    # =================================================================

    def _read_proxmox_credentials(self) -> dict[str, str]:
        """Parse Proxmox API token and SSH password from credentials.auto.tfvars.

        Returns a dict with keys: proxmox_api_url, proxmox_api_token, proxmox_ssh_password.
        """
        settings = get_settings()
        creds_path = self.repo_root / settings.credentials_tfvars_path
        result = {}
        if creds_path.exists():
            for line in creds_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"')
                if key in ("proxmox_api_url", "proxmox_api_token", "proxmox_ssh_password"):
                    result[key] = value
        return result

    async def _step_generate_secrets(self, step_id: int) -> bool:
        """Step 17: Generate and apply K8s secrets for CleanRoom apps.

        Creates secrets for cleanroom-db, scanning-console, and portal.
        Steps 11-15 already created secrets for openvas, faraday, metasploit.
        Also writes SOPS-encrypted YAML files and the credential vault.
        """
        await self.log(step_id, "info", "Generating secrets for CleanRoom applications...")

        settings = get_settings()
        sops_key_file = os.environ.get(
            "SOPS_AGE_KEY_FILE",
            os.path.expanduser("~/.config/sops/age/keys.txt"),
        )
        env = {"SOPS_AGE_KEY_FILE": sops_key_file}

        # --- 1. Create K8s secrets for the 3 new services ---

        # CleanRoom DB
        await self.k8s.ensure_namespace("cleanroom-db")
        db_password = self._generate_password()
        await self._create_secret(step_id, "cleanroom-db", "cleanroom-db-credentials",
                                  {"postgres-password": db_password})
        self.credentials["cleanroom_db"] = {"username": "cleanroom", "password": db_password}

        # Scanning Console
        await self.k8s.ensure_namespace("scanning-console")
        sc_admin_password = self._generate_password(16)
        sc_secret_key = self._generate_password(48)
        db_url = f"postgresql+asyncpg://cleanroom:{db_password}@cleanroom-db.cleanroom-db.svc.cluster.local:5432/cleanroom"

        # Generate bcrypt hash for admin password
        hash_result = await self.process_manager.run_command_simple(
            ["python3", "-c",
             f"import bcrypt; print(bcrypt.hashpw(b'{sc_admin_password}', bcrypt.gensalt(10)).decode())"],
            timeout=15,
        )
        sc_admin_hash = hash_result.output.strip() if hash_result.success else ""

        # Read Proxmox credentials for Target Lab integration
        proxmox_creds = self._read_proxmox_credentials()
        proxmox_api_url = proxmox_creds.get("proxmox_api_url", "")
        proxmox_api_token = proxmox_creds.get("proxmox_api_token", "")

        sc_secret_data = {
            "secret-key": sc_secret_key,
            "database-url": db_url,
            "admin-password-hash": sc_admin_hash,
        }
        if proxmox_api_url:
            sc_secret_data["proxmox-api-url"] = proxmox_api_url
        if proxmox_api_token:
            sc_secret_data["proxmox-api-token"] = proxmox_api_token
        await self._create_secret(step_id, "scanning-console", "scanning-console-credentials",
                                  sc_secret_data)
        self.credentials["scanning_console"] = {"username": "admin", "password": sc_admin_password}

        # Portal (shares SECRET_KEY with Scanning Console for SSO)
        await self.k8s.ensure_namespace("portal")
        await self._create_secret(step_id, "portal", "portal-credentials", {
            "secret-key": sc_secret_key,
        })
        self.credentials["portal"] = {"username": "admin", "password": "admin", "note": "Default"}

        # Threat Dragon (keys for Threat Dragon — step 14 doesn't create secrets)
        await self.k8s.ensure_namespace("threat-dragon")
        td_enc = self._generate_password(32)
        td_jwt = self._generate_password(32)
        td_refresh = self._generate_password(32)
        await self._create_secret(step_id, "threat-dragon", "threat-dragon-secrets", {
            "encryption-keys": td_enc,
            "jwt-signing-key": td_jwt,
            "jwt-refresh-signing-key": td_refresh,
        })

        self._save_state()

        # --- 2. Write SOPS-encrypted YAML files ---
        await self.log(step_id, "info", "Writing SOPS-encrypted secret files...")

        # Helper to write + encrypt one SOPS file
        async def write_sops_file(rel_path: str, content: str) -> bool:
            filepath = self.repo_root / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            # Run from repo root so SOPS finds .sops.yaml config
            result = await self.process_manager.run_command(
                ["sops", "-e", "-i", rel_path],
                cwd=self.repo_root,
                env=env,
                on_output=self._sanitized_output_callback(step_id),
            )
            if result.success:
                await self.log(step_id, "info", f"  Encrypted: {rel_path}")
            else:
                await self.log(step_id, "warn", f"  SOPS encrypt failed for {rel_path}: {result.output[:200]}")
            return result.success

        # CleanRoom DB
        await write_sops_file("apps/cleanroom-db/secrets.sops.yaml", (
            "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: cleanroom-db-credentials\n"
            "  namespace: cleanroom-db\ntype: Opaque\nstringData:\n"
            f'  postgres-password: "{db_password}"\n'
        ))

        # Scanning Console
        sc_sops_content = (
            "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: scanning-console-credentials\n"
            "  namespace: scanning-console\ntype: Opaque\nstringData:\n"
            f'  secret-key: "{sc_secret_key}"\n'
            f'  database-url: "{db_url}"\n'
            f'  admin-password-hash: "{sc_admin_hash}"\n'
        )
        if proxmox_api_url:
            sc_sops_content += f'  proxmox-api-url: "{proxmox_api_url}"\n'
        if proxmox_api_token:
            sc_sops_content += f'  proxmox-api-token: "{proxmox_api_token}"\n'
        await write_sops_file("apps/scanning-console/secrets.sops.yaml", sc_sops_content)

        # Portal
        await write_sops_file("apps/portal/secrets.sops.yaml", (
            "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: portal-credentials\n"
            "  namespace: portal\ntype: Opaque\nstringData:\n"
            f'  secret-key: "{sc_secret_key}"\n'
        ))

        # Threat Dragon
        await write_sops_file("apps/threat-dragon/secrets.sops.yaml", (
            "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: threat-dragon-secrets\n"
            "  namespace: threat-dragon\ntype: Opaque\nstringData:\n"
            f'  encryption-keys: "{td_enc}"\n'
            f'  jwt-signing-key: "{td_jwt}"\n'
            f'  jwt-refresh-signing-key: "{td_refresh}"\n'
        ))

        # --- 3. Generate credential vault for Portal ---
        await self.log(step_id, "info", "Generating credential vault for Portal...")

        openvas_pw = self.credentials.get("openvas", {}).get("password", "")
        faraday_pw = self.credentials.get("faraday", {}).get("password", "")
        traefik_pw = self.credentials.get("traefik", {}).get("password", "admin")

        vault_yaml = (
            f'- service: ArgoCD\n  url: https://argocd.knowledgeondemand.net\n  username: admin\n  password: "admin"\n'
            f'- service: OpenVAS\n  url: https://openvas.knowledgeondemand.net\n  username: admin\n  password: "{openvas_pw}"\n'
            f'- service: Faraday\n  url: https://faraday.knowledgeondemand.net\n  username: admin\n  password: "{faraday_pw}"\n'
            f'- service: Harbor\n  url: https://harbor.knowledgeondemand.net\n  username: admin\n  password: "Harbor12345"\n'
            f'- service: Scanning Console\n  url: https://scan.knowledgeondemand.net\n  username: admin\n  password: "{sc_admin_password}"\n'
            f'- service: Traefik Dashboard\n  url: https://traefik.knowledgeondemand.net\n  username: admin\n  password: "{traefik_pw}"\n'
            f'- service: Portal\n  url: https://cleanroom.knowledgeondemand.net\n  username: admin\n  password: "admin"\n'
        )
        # Create the K8s secret (ArgoCD excludes *.sops.yaml, so this won't be synced from git)
        await self._create_secret(step_id, "portal", "credential-vault",
                                  {"credentials.yaml": vault_yaml})

        # Indent vault_yaml for stringData block
        indented_vault = "\n".join("    " + line for line in vault_yaml.splitlines())

        await write_sops_file("apps/portal/credential-vault.sops.yaml", (
            "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: credential-vault\n"
            "  namespace: portal\ntype: Opaque\nstringData:\n  credentials.yaml: |\n"
            f"{indented_vault}\n"
        ))

        self._save_state()
        await self.log(step_id, "info", "Secret generation complete")
        return True

    async def _step_commit_push_secrets(self, step_id: int) -> bool:
        """Step 18: Commit and push SOPS-encrypted secrets to git.

        Adds encrypted secret files to git, verifies they contain SOPS
        headers (not plaintext), commits, and pushes.
        """
        await self.log(step_id, "info", "Committing secrets to git...")

        # Check for changes to commit
        diff_result = await self.process_manager.run_command_simple(
            ["git", "diff", "--name-only", "--", "apps/*/secrets.sops.yaml",
             "apps/portal/credential-vault.sops.yaml"],
            cwd=self.repo_root,
        )
        untracked = await self.process_manager.run_command_simple(
            ["git", "ls-files", "--others", "--exclude-standard", "--",
             "apps/*/secrets.sops.yaml", "apps/portal/credential-vault.sops.yaml"],
            cwd=self.repo_root,
        )

        changed_files = [
            f for f in (diff_result.output + "\n" + untracked.output).strip().splitlines() if f.strip()
        ]

        if not changed_files:
            await self.log(step_id, "info", "No secret file changes to commit — skipping")
            return True

        # Verify files contain SOPS header (not plaintext)
        for f in changed_files:
            filepath = self.repo_root / f
            if filepath.exists():
                content = filepath.read_text(errors="replace")[:200]
                if "sops:" not in content and "ENC[" not in content:
                    await self.log(step_id, "error",
                                   f"PLAINTEXT SECRET DETECTED in {f} — refusing to commit")
                    return False

        # Verify branch
        branch_result = await self.process_manager.run_command_simple(
            ["git", "branch", "--show-current"], cwd=self.repo_root,
        )
        current_branch = (branch_result.output or "").strip()
        await self.log(step_id, "info", f"Current branch: {current_branch}")

        # Stage files
        stage_cmd = ["git", "add"] + [str(f) for f in changed_files]
        stage_result = await self.process_manager.run_command(
            stage_cmd, cwd=self.repo_root,
            on_output=self._sanitized_output_callback(step_id),
        )
        if not stage_result.success:
            await self.log(step_id, "error", f"git add failed: {stage_result.output}")
            return False

        # Check if anything is actually staged
        staged_check = await self.process_manager.run_command_simple(
            ["git", "diff", "--cached", "--quiet"], cwd=self.repo_root,
        )
        if staged_check.success:
            await self.log(step_id, "info", "Nothing staged — secrets unchanged")
            return True

        # Commit
        commit_result = await self.process_manager.run_command(
            ["git", "commit", "-m", "chore: regenerate SOPS-encrypted secrets [automated]"],
            cwd=self.repo_root,
            on_output=self._sanitized_output_callback(step_id),
        )
        if not commit_result.success:
            await self.log(step_id, "error", f"git commit failed: {commit_result.output}")
            return False

        # Push
        push_result = await self.process_manager.run_command(
            ["git", "push", "origin", current_branch],
            cwd=self.repo_root,
            on_output=self._sanitized_output_callback(step_id),
        )
        if not push_result.success:
            await self.log(step_id, "warn", f"git push failed (non-fatal): {push_result.output[:200]}")
            # Non-fatal — secrets are already applied in K8s
        else:
            await self.log(step_id, "info", "Secrets pushed to git successfully")

        return True

    async def _step_deploy_build_vm(self, step_id: int) -> bool:
        """Step 19: Deploy and configure the Build VM LXC container.

        Uses Terraform to create the LXC, then configures it via Proxmox
        SSH + pct exec (user creation, SSH keys, repo clone, Docker install).
        """
        await self.log(step_id, "info", "Deploying Build VM...")

        settings = get_settings()
        proxmox_creds = self._read_proxmox_credentials()

        if not proxmox_creds.get("proxmox_api_token"):
            await self.log(step_id, "error",
                           f"Proxmox credentials not found in {settings.credentials_tfvars_path}")
            return False

        # Generate Build VM passwords
        root_password = self._generate_password()
        ssh_user_password = self._generate_password()

        self.credentials["build_vm"] = {
            "username": settings.build_vm_ssh_user,
            "password": ssh_user_password,
            "ip": settings.build_vm_ip,
            "note": "Build VM SSH access",
        }
        self._save_state()

        # --- Write terraform.tfvars ---
        terraform_dir = self.repo_root / "terraform" / "build-lxc"
        tfvars_path = terraform_dir / "terraform.tfvars"

        await self.log(step_id, "info", "Writing Terraform configuration...")
        tfvars_content = f"""# Auto-generated by deployment service
# Proxmox Connection
proxmox_api_url      = "{proxmox_creds.get('proxmox_api_url', '')}"
proxmox_api_token    = "{proxmox_creds.get('proxmox_api_token', '')}"
proxmox_ssh_user     = "{settings.proxmox_ssh_user}"
proxmox_ssh_password = "{proxmox_creds.get('proxmox_ssh_password', '')}"
proxmox_node         = ""
proxmox_pool         = ""

# LXC Container Configuration
lxc_vmid      = {settings.build_vm_vmid}
lxc_hostname  = "build-vm"
lxc_cores     = 2
lxc_memory    = 4096
lxc_swap      = 512
lxc_disk_size = 50
lxc_storage   = "local-lvm"
lxc_tags      = ["build", "docker", "management"]

# Template
template_storage      = "cephfs"
lxc_template_filename = "debian-12-standard_12.12-1_amd64.tar.zst"

# Network
network_bridge  = "vmbr0"
vlan_id         = {settings.build_vm_vlan_id}
lxc_ip_address  = "{settings.build_vm_ip}/24"
lxc_gateway     = "{settings.build_vm_gateway}"
lxc_mac_address = ""

# DNS
dns_domain  = "knowledgeondemand.net"
dns_servers = ["1.1.1.1", "8.8.8.8"]

# Auth
lxc_root_password = "{root_password}"
ssh_public_keys   = []

# SSH User
ssh_user          = "{settings.build_vm_ssh_user}"
ssh_user_password = "{ssh_user_password}"
ssh_user_groups   = "sudo,docker"
"""
        tfvars_path.write_text(tfvars_content)

        # --- Terraform init + apply ---
        await self.log(step_id, "info", "Running Terraform init...")
        init_result = await self.process_manager.run_command(
            ["terraform", "init"],
            cwd=terraform_dir,
            on_output=self._sanitized_output_callback(step_id),
        )
        if not init_result.success:
            await self.log(step_id, "error", f"Terraform init failed: {init_result.output[:300]}")
            return False

        await self.log(step_id, "info", "Running Terraform apply...")
        apply_result = await self.process_manager.run_command(
            ["terraform", "apply", "-auto-approve"],
            cwd=terraform_dir,
            on_output=self._sanitized_output_callback(step_id),
        )
        if not apply_result.success:
            await self.log(step_id, "error", "Terraform apply failed")
            return False

        await self.log(step_id, "info", f"Build VM container deployed at {settings.build_vm_ip}")

        # --- Setup via Proxmox SSH + pct exec ---
        await self.log(step_id, "info", "Configuring Build VM via pct exec...")

        proxmox_ssh_pw = proxmox_creds.get("proxmox_ssh_password", "")
        proxmox_host = settings.proxmox_host

        # Read GitHub SSH key
        github_key_path = Path.home() / ".ssh" / "github_deploy_key"
        if not github_key_path.exists():
            # Try alternative paths
            for alt in [Path("/root/.ssh/github_deploy_key"), Path.home() / ".ssh" / "id_ed25519"]:
                if alt.exists():
                    github_key_path = alt
                    break

        github_key_content = ""
        if github_key_path.exists():
            github_key_content = github_key_path.read_text()
            await self.log(step_id, "info", f"Using SSH key: {github_key_path}")
        else:
            await self.log(step_id, "warn", "No GitHub SSH key found — repo clone may fail")

        # Get git branch
        branch_result = await self.process_manager.run_command_simple(
            ["git", "branch", "--show-current"], cwd=self.repo_root,
        )
        git_branch = (branch_result.output or "").strip() or "refactor/restructure"

        # Build the pct exec setup script
        setup_script = f"""set -e
echo "=== Installing packages ==="
apt-get update && apt-get install -y sudo git locales sshpass
sed -i "s/# en_US.UTF-8/en_US.UTF-8/" /etc/locale.gen
locale-gen en_US.UTF-8

echo "=== Creating SSH user: {settings.build_vm_ssh_user} ==="
useradd -m -s /bin/bash -G sudo {settings.build_vm_ssh_user} 2>/dev/null || echo "User exists"
echo "{settings.build_vm_ssh_user}:{ssh_user_password}" | chpasswd
echo "{settings.build_vm_ssh_user} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/{settings.build_vm_ssh_user}
chmod 440 /etc/sudoers.d/{settings.build_vm_ssh_user}

echo "=== Disabling root SSH login ==="
sed -i "s/^#*PermitRootLogin.*/PermitRootLogin no/" /etc/ssh/sshd_config
systemctl restart ssh

echo "=== Setting up GitHub SSH key ==="
SSH_USER_HOME="/home/{settings.build_vm_ssh_user}"
mkdir -p ${{SSH_USER_HOME}}/.ssh
chmod 700 ${{SSH_USER_HOME}}/.ssh
cat > ${{SSH_USER_HOME}}/.ssh/github_deploy_key << 'KEYEOF'
{github_key_content}
KEYEOF
chmod 600 ${{SSH_USER_HOME}}/.ssh/github_deploy_key
cat > ${{SSH_USER_HOME}}/.ssh/config << 'SSHCONFIG'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_deploy_key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
SSHCONFIG
chmod 600 ${{SSH_USER_HOME}}/.ssh/config
chown -R {settings.build_vm_ssh_user}:{settings.build_vm_ssh_user} ${{SSH_USER_HOME}}/.ssh

mkdir -p /root/.ssh && chmod 700 /root/.ssh
cp ${{SSH_USER_HOME}}/.ssh/github_deploy_key /root/.ssh/
cp ${{SSH_USER_HOME}}/.ssh/config /root/.ssh/
chmod 600 /root/.ssh/github_deploy_key /root/.ssh/config
ssh-keyscan -t ed25519,rsa github.com >> /root/.ssh/known_hosts 2>/dev/null

echo "=== Cloning repository (branch: {git_branch}) ==="
mkdir -p /opt/talos-cleanroom
chown {settings.build_vm_ssh_user}:{settings.build_vm_ssh_user} /opt/talos-cleanroom
su - {settings.build_vm_ssh_user} -c "git clone -b {git_branch} git@github.com:williamdemarigny/Talos-CleanRoom.git /opt/talos-cleanroom"
git config --global --add safe.directory /opt/talos-cleanroom

echo "=== Running setup script ==="
cd /opt/talos-cleanroom/build-vm/scripts
chmod +x setup-lxc.sh
./setup-lxc.sh

echo "=== Adding user to docker group ==="
usermod -aG docker {settings.build_vm_ssh_user} 2>/dev/null || echo "docker group not ready"

echo "=== Configuring Docker to trust Harbor registry ==="
echo | openssl s_client -connect harbor.knowledgeondemand.net:443 \
    -servername harbor.knowledgeondemand.net 2>/dev/null \
    | openssl x509 > /usr/local/share/ca-certificates/harbor.crt 2>/dev/null || true
update-ca-certificates 2>/dev/null || true
systemctl restart docker

echo "=== Setup Complete ==="
"""
        # Write setup script to temp file, then run via sshpass + pct exec
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(setup_script)
            setup_script_path = f.name

        try:
            # Execute pct exec via SSH to Proxmox host
            pct_result = await self.process_manager.run_command(
                ["sshpass", "-p", proxmox_ssh_pw,
                 "ssh", "-o", "StrictHostKeyChecking=no",
                 f"{settings.proxmox_ssh_user}@{proxmox_host}",
                 f"pct exec {settings.build_vm_vmid} -- bash -s"],
                on_output=self._sanitized_output_callback(step_id),
                timeout=600,  # 10 minutes for full setup
            )
            # Feed the script via the process manager's stdin auto-send
            # Since process_manager sends "y\n" to stdin, we need a different approach
            # Use bash -c with the script inline instead
        finally:
            try:
                os.unlink(setup_script_path)
            except OSError:
                pass

        # Actually, run the setup via a different approach — SCP script then execute
        # First, copy script to Proxmox host, then pct push + exec
        await self.log(step_id, "info", "Executing setup via Proxmox SSH...")

        # Write the script and transfer it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(setup_script)
            setup_script_path = f.name

        try:
            # SCP script to Proxmox host
            scp_result = await self.process_manager.run_command_simple(
                ["sshpass", "-p", proxmox_ssh_pw,
                 "scp", "-o", "StrictHostKeyChecking=no",
                 setup_script_path,
                 f"{settings.proxmox_ssh_user}@{proxmox_host}:/tmp/build-vm-setup.sh"],
                timeout=30,
            )
            if not scp_result.success:
                await self.log(step_id, "error", f"Failed to copy setup script to Proxmox: {scp_result.output}")
                return False

            # Push script into container and execute
            exec_result = await self.process_manager.run_command(
                ["sshpass", "-p", proxmox_ssh_pw,
                 "ssh", "-o", "StrictHostKeyChecking=no",
                 f"{settings.proxmox_ssh_user}@{proxmox_host}",
                 f"pct push {settings.build_vm_vmid} /tmp/build-vm-setup.sh /tmp/setup.sh && "
                 f"pct exec {settings.build_vm_vmid} -- bash /tmp/setup.sh && "
                 f"rm -f /tmp/build-vm-setup.sh"],
                on_output=self._sanitized_output_callback(step_id),
                timeout=600,
            )
            if not exec_result.success:
                await self.log(step_id, "error", "Build VM setup failed")
                return False
        finally:
            try:
                os.unlink(setup_script_path)
            except OSError:
                pass

        # --- Copy kubeconfig to Build VM ---
        await self.log(step_id, "info", "Copying kubeconfig to Build VM...")
        container_ip = settings.build_vm_ip.split("/")[0]
        ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"

        # Wait for SSH to be ready
        for attempt in range(12):
            ssh_check = await self.process_manager.run_command_simple(
                ["sshpass", "-p", ssh_user_password,
                 "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"{settings.build_vm_ssh_user}@{container_ip}", "echo ok"],
                timeout=15,
            )
            if ssh_check.success and "ok" in (ssh_check.output or ""):
                break
            await self.log(step_id, "info", f"Waiting for Build VM SSH... ({attempt + 1}/12)")
            await asyncio.sleep(5)

        kubeconfig_path = Path.home() / ".kube" / "config"
        if kubeconfig_path.exists():
            push_result = await self.process_manager.run_command_simple(
                ["bash", "-c",
                 f"sshpass -p '{ssh_user_password}' scp {ssh_opts} "
                 f"{kubeconfig_path} {settings.build_vm_ssh_user}@{container_ip}:/tmp/kubeconfig && "
                 f"sshpass -p '{ssh_user_password}' ssh {ssh_opts} "
                 f"{settings.build_vm_ssh_user}@{container_ip} "
                 f"'mkdir -p ~/.kube && mv /tmp/kubeconfig ~/.kube/config && chmod 600 ~/.kube/config && "
                 f"sudo cp ~/.kube/config /root/.kube/config && sudo chmod 600 /root/.kube/config'"],
                timeout=30,
            )
            if push_result.success:
                await self.log(step_id, "info", "Kubeconfig copied to Build VM")
            else:
                await self.log(step_id, "warn", f"Kubeconfig copy failed: {push_result.output[:200]}")

        await self.log(step_id, "info", "Build VM deployment complete")
        return True

    async def _step_prepare_target_templates(self, step_id: int) -> bool:
        """Step 20: Prepare Metasploitable3 VM templates on Proxmox.

        SSHs to a Proxmox node and runs the template preparation script
        which downloads Vagrant boxes, converts VMDK to QCOW2, and creates
        VM templates (VMIDs 4000, 4001). Idempotent — skips if templates exist.
        """
        await self.log(step_id, "info", "Preparing Metasploitable3 target VM templates...")

        proxmox_creds = self._read_proxmox_credentials()
        proxmox_ssh_password = proxmox_creds.get("proxmox_ssh_password", "")
        if not proxmox_ssh_password:
            await self.log(step_id, "warn", "Proxmox SSH password not available — skipping template preparation")
            await self.log(step_id, "info", "Run scripts/prepare-metasploitable3-templates.sh manually on a Proxmox node")
            return True  # Non-fatal, templates can be created later

        # SSH to first Proxmox node
        settings = get_settings()
        proxmox_ip = settings.node_ips[0] if settings.node_ips else ""
        if not proxmox_ip:
            await self.log(step_id, "warn", "No Proxmox node IPs configured — skipping")
            return True

        # Use the management IP (VLAN 2) — derive from node IP pattern
        # Node IPs are on VLAN 3 (10.83.3.x), Proxmox mgmt is VLAN 2 (10.83.2.x)
        parts = proxmox_ip.split(".")
        if len(parts) == 4:
            mgmt_ip = f"{parts[0]}.{parts[1]}.2.{parts[3]}"
        else:
            mgmt_ip = proxmox_ip

        ssh_prefix = [
            "sshpass", "-p", proxmox_ssh_password,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"root@{mgmt_ip}",
        ]

        # Check if templates already exist (idempotent)
        check_result = await self.process_manager.run_command_simple(
            ssh_prefix + ["qm status 4000 2>/dev/null && qm status 4001 2>/dev/null"],
            timeout=30,
        )
        if check_result.success:
            await self.log(step_id, "info", "Templates already exist (VMIDs 4000, 4001) — skipping download")
            return True

        # Copy and execute the preparation script
        script_path = str(self.repo_root / "scripts" / "prepare-metasploitable3-templates.sh")

        scp_cmd = [
            "sshpass", "-p", proxmox_ssh_password,
            "scp", "-o", "StrictHostKeyChecking=no",
            script_path, f"root@{mgmt_ip}:/tmp/prepare-ms3.sh",
        ]
        scp_result = await self.process_manager.run_command(
            scp_cmd,
            on_output=self._sanitized_output_callback(step_id),
            timeout=30,
        )
        if not scp_result.success:
            await self.log(step_id, "warn", "Failed to copy template script to Proxmox node")
            await self.log(step_id, "info", "Run scripts/prepare-metasploitable3-templates.sh manually")
            return True  # Non-fatal

        # Execute the script (allow 20 minutes for ~6.5 GB download + conversion)
        await self.log(step_id, "info", "Downloading and converting Metasploitable3 images (this takes 10-15 minutes)...")
        exec_result = await self.process_manager.run_command(
            ssh_prefix + ["bash /tmp/prepare-ms3.sh && rm -f /tmp/prepare-ms3.sh"],
            on_output=self._sanitized_output_callback(step_id),
            timeout=1200,  # 20 minutes
        )

        if not exec_result.success:
            await self.log(step_id, "warn", f"Template preparation had issues: {exec_result.output[-300:]}")
            await self.log(step_id, "info", "Target Lab may still work if templates were partially created")
            return True  # Non-fatal — deployment can continue

        await self.log(step_id, "info", "Metasploitable3 templates ready (VMIDs 4000, 4001)")
        return True

    async def _step_build_push_images(self, step_id: int) -> bool:
        """Step 20: Build and push container images from the Build VM.

        SSHs to the Build VM and runs existing build-and-push.sh scripts
        for LOKI-RS, Scanning Console, and Portal.
        """
        await self.log(step_id, "info", "Building and pushing container images...")

        settings = get_settings()
        container_ip = settings.build_vm_ip.split("/")[0]
        ssh_user = settings.build_vm_ssh_user
        ssh_password = self.credentials.get("build_vm", {}).get("password", "")

        if not ssh_password:
            await self.log(step_id, "error", "Build VM credentials not available")
            return False

        ssh_cmd_prefix = [
            "sshpass", "-p", ssh_password,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"{ssh_user}@{container_ip}",
        ]

        # Build scripts and their paths in the repo
        build_scripts = [
            ("LOKI-RS Scanner", "/opt/talos-cleanroom/apps/loki/build-and-push.sh"),
            ("Scanning Console", "/opt/talos-cleanroom/scanning-app/build-and-push.sh"),
            ("Portal", "/opt/talos-cleanroom/portal/build-and-push.sh"),
        ]

        # Harbor credentials for build scripts
        harbor_password = self.credentials.get("harbor", {}).get("password", "Harbor12345")

        for name, script_path in build_scripts:
            await self.log(step_id, "info", f"Building {name}...")
            build_result = await self.process_manager.run_command(
                ssh_cmd_prefix + [
                    f"cd $(dirname {script_path}) && "
                    f"sudo HARBOR_USER=admin HARBOR_PASSWORD='{harbor_password}' bash {script_path}"
                ],
                on_output=self._sanitized_output_callback(step_id),
                timeout=600,  # 10 minutes per build
            )
            if not build_result.success:
                await self.log(step_id, "error", f"Build failed for {name}")
                return False
            await self.log(step_id, "info", f"{name} built and pushed successfully")

        self.credentials["harbor"] = {
            "username": "admin", "password": "Harbor12345",
            "note": "Change on first login",
        }
        self._save_state()

        await self.log(step_id, "info", "All container images built and pushed to Harbor")
        return True

    async def _step_deploy_cleanroom_apps(self, step_id: int) -> bool:
        """Step 21: Deploy CleanRoom DB, Scanning Console, and Portal via ArgoCD."""
        await self.log(step_id, "info", "Deploying CleanRoom applications...")

        # Deploy all three apps
        for app in ["cleanroom-db", "scanning-console", "portal"]:
            if not await self._deploy_argocd_app(app, step_id):
                return False

        # Wait for CleanRoom DB first (Scanning Console depends on it)
        if not await self._wait_for_argocd_sync("cleanroom-db", step_id):
            return False

        # Then wait for remaining apps
        if not await self._wait_for_argocd_sync("scanning-console", step_id):
            return False
        if not await self._wait_for_argocd_sync("portal", step_id):
            return False

        # Log access info
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "CleanRoom applications deployed:")
        await self.log(step_id, "info", "  - Portal:           https://cleanroom.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Scanning Console: https://scan.knowledgeondemand.net")
        await self.log(step_id, "info", "  - CleanRoom DB:     Internal (cleanroom-db.cleanroom-db.svc)")

        return True

    async def _step_apply_network_policies(self, step_id: int) -> bool:
        """Step 22: Apply zero-trust network policies to all namespaces.

        Applied last because earlier steps need unrestricted network during setup.
        Applies each file individually so policies for non-existent namespaces
        are skipped rather than failing the entire step.
        """
        await self.log(step_id, "info", "Applying network policies...")

        netpol_dir = self.projects_dir / "network-policies"
        if not netpol_dir.exists():
            await self.log(step_id, "warn", f"Network policies directory not found: {netpol_dir}")
            return True  # Non-fatal

        # Discover which namespaces exist in the cluster
        ns_result = await self.process_manager.run_command(
            ["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
        )
        existing_namespaces = set(ns_result.output.strip().split()) if ns_result.success else set()
        if existing_namespaces:
            await self.log(step_id, "info", f"Found {len(existing_namespaces)} namespaces in cluster")

        # Collect YAML files (skip README, etc.)
        policy_files = sorted(f for f in netpol_dir.iterdir() if f.suffix in (".yaml", ".yml"))
        if not policy_files:
            await self.log(step_id, "warn", "No YAML files found in network-policies directory")
            return True

        applied = 0
        skipped = 0
        failed = 0
        all_success = True

        for policy_file in policy_files:
            try:
                content = policy_file.read_text()
            except OSError as e:
                await self.log(step_id, "error", f"Cannot read {policy_file.name}: {e}")
                failed += 1
                all_success = False
                continue

            # Split multi-document YAML and filter out docs targeting
            # namespaces that don't exist yet.
            docs = re.split(r'^---\s*$', content, flags=re.MULTILINE)
            applicable_docs = []
            file_skipped_ns: set[str] = set()

            for doc in docs:
                doc_stripped = doc.strip()
                if not doc_stripped or doc_stripped.startswith('#'):
                    continue
                # Extract namespace from this single document
                ns_matches = re.findall(r'^\s*namespace:\s*(\S+)', doc_stripped, re.MULTILINE)
                doc_ns = set(ns_matches)
                missing = doc_ns - existing_namespaces if existing_namespaces else set()
                if missing:
                    file_skipped_ns.update(missing)
                else:
                    applicable_docs.append(doc_stripped)

            if file_skipped_ns:
                await self.log(
                    step_id, "warn",
                    f"{policy_file.name}: skipping policies for missing namespace(s): "
                    f"{', '.join(sorted(file_skipped_ns))}"
                )

            if not applicable_docs:
                skipped += 1
                continue

            # Build filtered YAML and apply via stdin
            filtered_yaml = "\n---\n".join(applicable_docs)
            result = await self.process_manager.run_command(
                ["kubectl", "apply", "-f", "-"],
                stdin_data=filtered_yaml,
                on_output=self._sanitized_output_callback(step_id),
            )

            if result.success:
                applied += 1
            else:
                await self.log(step_id, "error", f"Failed to apply {policy_file.name}: {result.output[:200]}")
                failed += 1
                all_success = False

        await self.log(step_id, "info", f"Network policies: {applied} applied, {skipped} skipped, {failed} failed")

        # Final deployment summary (only on success)
        if all_success:
            await self.log(step_id, "info", "")
            await self.log(step_id, "info", "==========================================")
            await self.log(step_id, "info", "Full Platform Deployment Complete!")
            await self.log(step_id, "info", "==========================================")
            await self.log(step_id, "info", "")
            await self.log(step_id, "info", "Access services at:")
            await self.log(step_id, "info", "  - Portal:           https://cleanroom.knowledgeondemand.net")
            await self.log(step_id, "info", "  - Scanning Console: https://scan.knowledgeondemand.net")
            await self.log(step_id, "info", "  - ArgoCD:           https://argocd.knowledgeondemand.net")
            await self.log(step_id, "info", "  - OpenVAS:          https://openvas.knowledgeondemand.net")
            await self.log(step_id, "info", "  - Faraday:          https://faraday.knowledgeondemand.net")
            await self.log(step_id, "info", "  - Harbor:           https://harbor.knowledgeondemand.net")
            await self.log(step_id, "info", "  - Threat Dragon:    https://threatdragon.knowledgeondemand.net")
            await self.log(step_id, "info", "")
            await self.log(step_id, "info", "View credentials: Deployment > Credentials tab")
            await self.log(step_id, "info", "==========================================")

        return all_success


# Global deployment service instance
_deployment_service: Optional[DeploymentService] = None


def get_deployment_service() -> DeploymentService:
    """Get or create deployment service instance."""
    global _deployment_service
    if _deployment_service is None:
        _deployment_service = DeploymentService()
    return _deployment_service
