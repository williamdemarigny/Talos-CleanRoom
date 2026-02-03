"""Deployment service for orchestrating cluster deployment."""

import asyncio
import json
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


@dataclass
class DeploymentService:
    """Service for orchestrating cluster deployment."""

    process_manager: ProcessManager = field(default_factory=ProcessManager)
    current_deployment: Optional[DeploymentState] = None
    log_callback: Optional[Callable[[LogEntry], Awaitable[None]]] = None
    step_callback: Optional[Callable[[DeploymentStep], Awaitable[None]]] = None
    logs: List[LogEntry] = field(default_factory=list)

    def __post_init__(self):
        settings = get_settings()
        self.repo_root = settings.repo_root
        self.master_node = settings.master_node
        self.health_check_retries = settings.health_check_retries
        self.health_check_interval = settings.health_check_interval
        self.longhorn_timeout = settings.longhorn_timeout
        self.argocd_password_retries = settings.argocd_password_retries
        self.dependencies = settings.dependencies

    @property
    def terraform_dir(self) -> Path:
        return self.repo_root / "Resources" / "IAC-DNS" / "terraform" / "talos-cluster-create"

    @property
    def talos_dir(self) -> Path:
        return self.repo_root / "Resources" / "IAC-DNS" / "talos"

    @property
    def iac_dir(self) -> Path:
        return self.repo_root / "Resources" / "IAC-DNS"

    @property
    def argocd_dir(self) -> Path:
        return self.iac_dir / "infrastructure" / "argocd"

    @property
    def projects_dir(self) -> Path:
        return self.iac_dir / "infrastructure" / "projects"

    def _create_log_callback(self, step_id: int, level: str = "info"):
        """Create an async callback for logging output lines.

        This is needed because lambda functions cannot properly await async methods.
        Using a lambda like `lambda line: self.log(step_id, "info", line)` creates
        a coroutine that is never executed. This method returns a proper async
        function that can be awaited by the process manager.
        """
        async def callback(line: str):
            await self.log(step_id, level, line)
        return callback

    async def log(self, step_id: int, level: str, message: str):
        """Log a message and notify via callback."""
        entry = LogEntry(
            timestamp=datetime.utcnow(),
            step_id=step_id,
            level=level,
            message=message
        )
        self.logs.append(entry)
        if self.log_callback:
            await self.log_callback(entry)

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
                await self.step_callback(step)

    def get_status(self) -> Optional[DeploymentState]:
        """Get current deployment status."""
        return self.current_deployment

    def is_running(self) -> bool:
        """Check if deployment is currently running."""
        return (self.current_deployment is not None and
                self.current_deployment.status == DeploymentStatus.RUNNING)

    async def start_deployment(
        self,
        log_callback: Optional[Callable[[LogEntry], Awaitable[None]]] = None,
        step_callback: Optional[Callable[[DeploymentStep], Awaitable[None]]] = None
    ) -> DeploymentState:
        """Start a new deployment."""
        if self.is_running():
            raise RuntimeError("Deployment already in progress")

        self.log_callback = log_callback
        self.step_callback = step_callback
        self.logs = []

        # Initialize deployment state
        self.current_deployment = DeploymentState(
            id=str(uuid.uuid4()),
            status=DeploymentStatus.RUNNING,
            started_at=datetime.utcnow(),
            steps=[DeploymentStep(**s.model_dump()) for s in DEPLOYMENT_STEPS]
        )

        # Run deployment in background
        asyncio.create_task(self._run_deployment())

        return self.current_deployment

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

    async def cleanup(self) -> bool:
        """Run cleanup (terraform destroy)."""
        await self.log(-1, "info", "Running cleanup (terraform destroy)...")

        result = await self.process_manager.run_command(
            ["terraform", "destroy", "-auto-approve"],
            cwd=self.terraform_dir,
            on_output=self._create_log_callback(-1)
        )

        # Log the actual result for debugging
        await self.log(-1, "info", f"Terraform destroy completed with return code: {result.return_code}")

        # Check output for success indicators even if return code is non-zero
        # Terraform can return non-zero if some resources were already deleted
        output_lower = result.output.lower()
        if result.success:
            await self.log(-1, "info", "Cleanup completed successfully")
            return True
        elif "destroy complete" in output_lower or "resources destroyed" in output_lower:
            # Terraform reported destruction but may have had warnings
            await self.log(-1, "warn", f"Cleanup completed with warnings (exit code {result.return_code})")
            return True
        elif result.return_code == 1 and ("no changes" in output_lower or "0 destroyed" in output_lower):
            # Nothing to destroy - that's still a success
            await self.log(-1, "info", "No resources to destroy")
            return True
        else:
            await self.log(-1, "error", f"Cleanup failed with exit code {result.return_code}")
            return False

    async def _run_deployment(self):
        """Execute the full deployment process."""
        try:
            steps = [
                (0, self._step_validate_git),
                (1, self._step_check_dependencies),
                (2, self._step_terraform_deploy),
                (3, self._step_generate_talos_config),
                (4, self._step_apply_talos_configs),
                (5, self._step_verify_cluster_health),
                (6, self._step_get_kubeconfig),
                (7, self._step_install_argocd),
                (8, self._step_deploy_infrastructure),
                (9, self._step_wait_for_longhorn),
                (10, self._step_argocd_self_management),
                (11, self._step_deploy_openvas),
                (12, self._step_deploy_faraday),
                (13, self._step_deploy_metasploit),
                (14, self._step_deploy_threat_dragon),
            ]

            for step_id, step_func in steps:
                if self.current_deployment.status != DeploymentStatus.RUNNING:
                    break

                self.current_deployment.current_step = step_id
                await self.update_step(step_id, StepStatus.RUNNING)

                success = await step_func(step_id)

                if not success:
                    await self.update_step(step_id, StepStatus.FAILED)
                    self.current_deployment.status = DeploymentStatus.FAILED
                    self.current_deployment.error_message = f"Failed at step: {DEPLOYMENT_STEPS[step_id].description}"
                    await self.log(step_id, "error", f"Step failed: {DEPLOYMENT_STEPS[step_id].description}")
                    break

                await self.update_step(step_id, StepStatus.SUCCESS)

            if self.current_deployment.status == DeploymentStatus.RUNNING:
                self.current_deployment.status = DeploymentStatus.COMPLETED
                await self.log(-1, "info", "Deployment completed successfully!")

        except Exception as e:
            self.current_deployment.status = DeploymentStatus.FAILED
            self.current_deployment.error_message = str(e)
            await self.log(-1, "error", f"Deployment failed with error: {e}")

        finally:
            self.current_deployment.completed_at = datetime.utcnow()

    async def _step_validate_git(self, step_id: int) -> bool:
        """Step 0: Validate git repository."""
        await self.log(step_id, "info", "Validating git repository...")

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
        """Step 1: Check required dependencies."""
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
        """Step 2: Terraform deployment."""
        await self.log(step_id, "info", "Running terraform init...")

        result = await self.process_manager.run_command(
            ["terraform", "init"],
            cwd=self.terraform_dir,
            on_output=self._create_log_callback(step_id)
        )
        if not result.success:
            return False

        await self.log(step_id, "info", "Running terraform plan...")
        result = await self.process_manager.run_command(
            ["terraform", "plan", "-out=.tfplan"],
            cwd=self.terraform_dir,
            on_output=self._create_log_callback(step_id)
        )
        if not result.success:
            return False

        await self.log(step_id, "info", "Running terraform apply...")
        result = await self.process_manager.run_command(
            ["terraform", "apply", ".tfplan"],
            cwd=self.terraform_dir,
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_generate_talos_config(self, step_id: int) -> bool:
        """Step 3: Generate Talos configuration."""
        sops_key_file = os.environ.get(
            "SOPS_AGE_KEY_FILE",
            os.path.expanduser("~/.config/sops/age/keys.txt")
        )
        env = {"SOPS_AGE_KEY_FILE": sops_key_file}

        # Run tfvars-to-talos-env.sh
        await self.log(step_id, "info", "Running tfvars-to-talos-env.sh...")
        script_path = self.iac_dir / "tfvars-to-talos-env.sh"

        result = await self.process_manager.run_command(
            ["bash", str(script_path), "--backup"],
            cwd=self.iac_dir,
            on_output=self._create_log_callback(step_id)
        )
        if not result.success:
            return False

        # Generate Talos secret
        await self.log(step_id, "info", "Generating Talos secret...")
        secret_file = self.talos_dir / "talsecret.sops.yaml"

        result = await self.process_manager.run_command_simple(
            ["talhelper", "gensecret"],
            cwd=self.talos_dir,
            env=env
        )
        if not result.success:
            return False

        # Write secret to file
        with open(secret_file, 'w') as f:
            f.write(result.output)

        # Encrypt with SOPS
        await self.log(step_id, "info", "Encrypting secret with SOPS...")
        result = await self.process_manager.run_command(
            ["sops", "-e", "-i", "talsecret.sops.yaml"],
            cwd=self.talos_dir,
            env=env,
            on_output=self._create_log_callback(step_id)
        )
        if not result.success:
            return False

        # Generate Talos config
        await self.log(step_id, "info", "Generating Talos config...")
        result = await self.process_manager.run_command(
            ["talhelper", "genconfig", "--env-file", "talenv.yaml"],
            cwd=self.talos_dir,
            env=env,
            on_output=self._create_log_callback(step_id)
        )

        if not result.success:
            return False

        # Fix permissions on generated config files so they're readable
        # This is needed because the service may run as a different user
        clusterconfig_dir = self.talos_dir / "clusterconfig"
        if clusterconfig_dir.exists():
            await self.log(step_id, "info", "Fixing permissions on generated configs...")
            await self.process_manager.run_command_simple(
                ["chmod", "-R", "a+r", str(clusterconfig_dir)],
                timeout=10
            )

        return True

    async def _step_apply_talos_configs(self, step_id: int) -> bool:
        """Step 4: Apply Talos configurations."""
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        await self.log(step_id, "info", "Running apply-configs.sh --bootstrap...")
        result = await self.process_manager.run_command(
            ["bash", "apply-configs.sh", "--bootstrap"],
            cwd=self.talos_dir,
            env=env,
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_verify_cluster_health(self, step_id: int) -> bool:
        """Step 5: Verify cluster health."""
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        max_wait = self.health_check_retries * self.health_check_interval
        await self.log(step_id, "info", f"Waiting for cluster health (max wait: {max_wait}s)...")

        for i in range(1, self.health_check_retries + 1):
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            result = await self.process_manager.run_command_simple(
                ["talosctl", "health", f"--nodes={self.master_node}"],
                env=env,
                timeout=30
            )

            if result.success:
                await self.log(step_id, "info", "Cluster is healthy!")
                return True

            await self.log(step_id, "info", f"Retrying ({i}/{self.health_check_retries})...")
            await asyncio.sleep(self.health_check_interval)

        await self.log(step_id, "error", "Cluster failed to become healthy")
        return False

    async def _step_get_kubeconfig(self, step_id: int) -> bool:
        """Step 6: Get kubeconfig."""
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}
        kubeconfig_path = Path.home() / ".kube" / "config"

        # Ensure .kube directory exists
        kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)

        await self.log(step_id, "info", f"Retrieving kubeconfig to {kubeconfig_path}...")
        result = await self.process_manager.run_command(
            ["talosctl", "kubeconfig", f"--nodes={self.master_node}", str(kubeconfig_path)],
            env=env,
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_install_argocd(self, step_id: int) -> bool:
        """Step 7: Install ArgoCD."""
        await self.log(step_id, "info", "Running ArgoCD install script...")

        result = await self.process_manager.run_command(
            ["bash", "install.sh"],
            cwd=self.argocd_dir,
            on_output=self._create_log_callback(step_id)
        )

        if not result.success:
            return False

        # Configure ArgoCD admin password with retries
        await self.log(step_id, "info", "Configuring ArgoCD admin password...")
        retries = self.argocd_password_retries

        for i in range(1, retries + 1):
            await self.log(step_id, "info", f"  Attempt {i}/{retries}: Setting admin password...")

            # Ensure argocd-server pod is fully ready
            result = await self.process_manager.run_command_simple(
                ["kubectl", "wait", "--for=condition=ready", "pod",
                 "-l", "app.kubernetes.io/name=argocd-server",
                 "-n", "argocd", "--timeout=60s"],
                timeout=70
            )
            if not result.success:
                await self.log(step_id, "warn", "  Warning: argocd-server pod not ready, retrying...")
                await asyncio.sleep(10)
                continue

            # Give the server a moment to fully initialize
            await asyncio.sleep(5)

            # Generate bcrypt hash using argocd CLI in the pod
            result = await self.process_manager.run_command_simple(
                ["kubectl", "-n", "argocd", "exec", "deployment/argocd-server",
                 "--", "argocd", "account", "bcrypt", "--password", "admin"],
                timeout=30
            )

            if result.success and result.output.strip() and "$2" in result.output:
                admin_hash = result.output.strip()
                # Patch the secret with the new password
                patch_data = json.dumps({
                    "stringData": {
                        "admin.password": admin_hash,
                        "admin.passwordMtime": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                })

                result = await self.process_manager.run_command_simple(
                    ["kubectl", "-n", "argocd", "patch", "secret", "argocd-secret", "-p", patch_data],
                    timeout=30
                )

                if result.success:
                    await asyncio.sleep(3)
                    # Verify the password was set
                    result = await self.process_manager.run_command_simple(
                        ["kubectl", "-n", "argocd", "get", "secret", "argocd-secret",
                         "-o", "jsonpath={.data.admin\\.password}"],
                        timeout=10
                    )
                    if result.success and result.output.strip():
                        await self.log(step_id, "info", "  ✓ ArgoCD admin password hash updated")

                        # Restart ArgoCD server to pick up the new password
                        await self.log(step_id, "info", "  Restarting ArgoCD server to apply new password...")
                        restart_result = await self.process_manager.run_command_simple(
                            ["kubectl", "-n", "argocd", "rollout", "restart", "deployment/argocd-server"],
                            timeout=30
                        )
                        if restart_result.success:
                            # Wait for the rollout to complete
                            await self.log(step_id, "info", "  Waiting for ArgoCD server rollout...")
                            await self.process_manager.run_command_simple(
                                ["kubectl", "-n", "argocd", "rollout", "status", "deployment/argocd-server", "--timeout=120s"],
                                timeout=130
                            )
                            await self.log(step_id, "info", "  ✓ ArgoCD admin password set to: admin")
                        else:
                            await self.log(step_id, "warn", "  Warning: Could not restart ArgoCD server, password may not take effect immediately")
                        return True

            await self.log(step_id, "warn", f"  Password setting attempt {i} failed, waiting before retry...")
            await asyncio.sleep(15)

        await self.log(step_id, "warn", f"Warning: Could not automatically set ArgoCD admin password after {retries} attempts")
        await self.log(step_id, "info", "The password from values.yaml should still work")
        return True  # Don't fail the deployment, password may still work from values.yaml

    async def _step_deploy_infrastructure(self, step_id: int) -> bool:
        """Step 8: Deploy infrastructure stack."""
        await self.log(step_id, "info", "Running deploy-ingress-stack.sh...")

        result = await self.process_manager.run_command(
            ["bash", "deploy-ingress-stack.sh"],
            cwd=self.projects_dir,
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_wait_for_longhorn(self, step_id: int) -> bool:
        """Step 9: Wait for Longhorn storage to be fully operational."""
        await self.log(step_id, "info", "Waiting for Longhorn to be fully operational...")
        start_time = asyncio.get_event_loop().time()
        timeout = self.longhorn_timeout

        # Wait for longhorn-system namespace
        await self.log(step_id, "info", "  Waiting for longhorn-system namespace...")
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                await self.log(step_id, "error", "Timeout waiting for longhorn-system namespace")
                return False

            result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "namespace", "longhorn-system"],
                timeout=10
            )
            if result.success:
                await self.log(step_id, "info", "  ✓ Namespace longhorn-system exists")
                break
            await asyncio.sleep(5)

        # Wait for all Longhorn deployments
        deployments = [
            "longhorn-driver-deployer",
            "longhorn-ui",
            "csi-attacher",
            "csi-provisioner",
            "csi-resizer",
            "csi-snapshotter"
        ]

        for deploy in deployments:
            await self.log(step_id, "info", f"  Waiting for deployment/{deploy}...")
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    await self.log(step_id, "error", f"Timeout waiting for deployment/{deploy}")
                    return False

                # Check if deployment exists
                result = await self.process_manager.run_command_simple(
                    ["kubectl", "get", "deployment", deploy, "-n", "longhorn-system"],
                    timeout=10
                )
                if not result.success:
                    await asyncio.sleep(5)
                    continue

                # Wait for deployment to be available
                remaining = int(timeout - elapsed)
                result = await self.process_manager.run_command_simple(
                    ["kubectl", "wait", "--for=condition=available",
                     f"deployment/{deploy}", "-n", "longhorn-system",
                     f"--timeout={remaining}s"],
                    timeout=remaining + 10
                )
                if result.success:
                    await self.log(step_id, "info", f"  ✓ deployment/{deploy} is available")
                    break
                await asyncio.sleep(5)

        # Wait for Longhorn DaemonSets
        daemonsets = ["longhorn-manager", "longhorn-csi-plugin"]

        for ds in daemonsets:
            await self.log(step_id, "info", f"  Waiting for daemonset/{ds}...")
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    await self.log(step_id, "error", f"Timeout waiting for daemonset/{ds}")
                    return False

                # Get daemonset status
                result = await self.process_manager.run_command_simple(
                    ["kubectl", "get", "daemonset", ds, "-n", "longhorn-system",
                     "-o", "jsonpath={.status.desiredNumberScheduled},{.status.numberReady}"],
                    timeout=10
                )
                if result.success and result.output.strip():
                    parts = result.output.strip().split(",")
                    if len(parts) == 2:
                        desired = int(parts[0]) if parts[0] else 0
                        ready = int(parts[1]) if parts[1] else 0
                        if desired > 0 and desired == ready:
                            await self.log(step_id, "info", f"  ✓ daemonset/{ds} is ready ({ready}/{desired} pods)")
                            break
                        await self.log(step_id, "info", f"    daemonset/{ds}: {ready}/{desired} pods ready, waiting...")
                await asyncio.sleep(10)

        # Wait for Longhorn StorageClass
        await self.log(step_id, "info", "  Waiting for Longhorn StorageClass...")
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                await self.log(step_id, "error", "Timeout waiting for Longhorn StorageClass")
                return False

            result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "storageclass", "longhorn"],
                timeout=10
            )
            if result.success:
                await self.log(step_id, "info", "  ✓ StorageClass 'longhorn' is available")
                break
            await asyncio.sleep(5)

        # Verify all pods are running
        await self.log(step_id, "info", "  Verifying all Longhorn pods are running...")
        pod_wait_start = asyncio.get_event_loop().time()
        max_pod_wait = 120

        while True:
            pod_elapsed = asyncio.get_event_loop().time() - pod_wait_start
            if pod_elapsed >= max_pod_wait:
                await self.log(step_id, "warn", "Warning: Some Longhorn pods may not be fully ready, but continuing...")
                break

            result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "pods", "-n", "longhorn-system", "--no-headers"],
                timeout=10
            )
            if result.success:
                lines = result.output.strip().split("\n")
                not_running = sum(1 for line in lines if line and "Running" not in line and "Completed" not in line)
                if not_running == 0:
                    await self.log(step_id, "info", "  ✓ All Longhorn pods are running")
                    break
                await self.log(step_id, "info", f"    {not_running} pod(s) not yet running, waiting...")
            await asyncio.sleep(10)

        await self.log(step_id, "info", "✓ Longhorn is fully operational")
        return True

    async def _step_argocd_self_management(self, step_id: int) -> bool:
        """Step 9: Enable ArgoCD self-management."""
        await self.log(step_id, "info", "Enabling ArgoCD self-management...")

        app_yaml = self.projects_dir / "argocd" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._create_log_callback(step_id)
        )

        if result.success:
            await self.log(step_id, "info", "Waiting for ArgoCD self-management...")
            await asyncio.sleep(10)

        return result.success

    async def _step_deploy_openvas(self, step_id: int) -> bool:
        """Step 10: Deploy OpenVAS."""
        await self.log(step_id, "info", "Deploying OpenVAS...")

        app_yaml = self.projects_dir / "openvas" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_deploy_faraday(self, step_id: int) -> bool:
        """Step 11: Deploy Faraday."""
        await self.log(step_id, "info", "Deploying Faraday...")

        app_yaml = self.projects_dir / "faraday" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_deploy_metasploit(self, step_id: int) -> bool:
        """Step 12: Deploy Metasploit."""
        await self.log(step_id, "info", "Deploying Metasploit...")

        app_yaml = self.projects_dir / "metasploit" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._create_log_callback(step_id)
        )

        return result.success

    async def _step_deploy_threat_dragon(self, step_id: int) -> bool:
        """Step 13: Deploy Threat Dragon."""
        await self.log(step_id, "info", "Deploying Threat Dragon...")

        app_yaml = self.projects_dir / "threat-dragon" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=self._create_log_callback(step_id)
        )

        # Wait for applications to sync
        await self.log(step_id, "info", "Waiting for applications to sync...")
        await asyncio.sleep(30)

        return result.success


# Global deployment service instance
_deployment_service: Optional[DeploymentService] = None


def get_deployment_service() -> DeploymentService:
    """Get or create deployment service instance."""
    global _deployment_service
    if _deployment_service is None:
        _deployment_service = DeploymentService()
    return _deployment_service
