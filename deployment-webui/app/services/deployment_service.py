"""Deployment service for orchestrating cluster deployment."""

import asyncio
import json
import re
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
            on_output=lambda line: self.log(-1, "info", line)
        )

        return result.success

    async def _run_deployment(self):
        """Execute the full deployment process."""
        try:
            steps = [
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
        await self.log(step_id, "info", "Waiting for VMs to boot and Talos API to become available...")
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
        max_attempts = 30
        interval = 10
        max_wait = max_attempts * interval

        await self.log(step_id, "info", f"Checking Talos API readiness (max wait: {max_wait}s per VM)...")

        for vm_name, details in vm_details.items():
            vmid = details.get("vmid")
            proxmox_node = details.get("proxmox_node", "")
            fqdn = details.get("fqdn", vm_name)

            await self.log(step_id, "info", f"Waiting for {vm_name} (VMID: {vmid})...")

            # Poll for DHCP IP from Proxmox guest agent, then check Talos API
            ready = False
            dhcp_ip = None

            for attempt in range(1, max_attempts + 1):
                if self.current_deployment.status != DeploymentStatus.RUNNING:
                    return False

                # Try to get DHCP IP from Proxmox guest agent if we have credentials
                # Keep retrying until we get an IP (guest agent may not be ready yet)
                if proxmox_endpoint and proxmox_token and proxmox_node:
                    try:
                        curl_result = subprocess.run(
                            ["curl", "-s", "-k", "-H", f"Authorization: PVEAPIToken={proxmox_token}",
                             f"{proxmox_endpoint}/api2/json/nodes/{proxmox_node}/qemu/{vmid}/agent/network-get-interfaces"],
                            capture_output=True, text=True, timeout=10
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
                        timeout=15
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

                await self.log(step_id, "info", f"  Attempt {attempt}/{max_attempts} - waiting {interval}s...")
                await asyncio.sleep(interval)

            if not ready:
                if not dhcp_ip:
                    await self.log(step_id, "error", f"  {vm_name}: Could not get DHCP IP from guest agent after {max_wait}s")
                else:
                    await self.log(step_id, "error", f"  {vm_name}: Talos API not ready at {dhcp_ip} after {max_wait}s")
                return False

        await self.log(step_id, "info", "All VMs are ready with Talos API available")
        return True

    async def _step_generate_talos_config(self, step_id: int) -> bool:
        """Step 4: Generate Talos configuration."""
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
        script_path = self.iac_dir / "tfvars-to-talos-env.sh"

        result = await self.process_manager.run_command(
            ["bash", str(script_path), "--force"],
            cwd=self.iac_dir,
            env=env,
            on_output=lambda line: self.log(step_id, "info", line)
        )
        if not result.success:
            await self.log(step_id, "error", f"tfvars-to-talos-env.sh failed: {result.output}")
            return False

        # Remove existing secret file to ensure fresh generation
        secret_file = self.talos_dir / "talsecret.sops.yaml"
        if secret_file.exists():
            await self.log(step_id, "info", "Removing existing talsecret.sops.yaml for fresh generation...")
            try:
                secret_file.unlink()
            except Exception as e:
                await self.log(step_id, "warn", f"Could not remove old secret file: {e}")

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
            ["sops", "-e", "-i", "talsecret.sops.yaml"],
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
        """Step 4: Apply Talos configurations."""
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
        """Step 5: Verify cluster health."""
        talosconfig = self.talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        max_wait = self.health_check_retries * self.health_check_interval
        await self.log(step_id, "info", f"Waiting for cluster health (max wait: {max_wait}s)...")
        await self.log(step_id, "info", f"Using TALOSCONFIG: {talosconfig}")
        await self.log(step_id, "info", f"Target node: {self.master_node}")

        for i in range(1, self.health_check_retries + 1):
            if self.current_deployment.status != DeploymentStatus.RUNNING:
                return False

            result = await self.process_manager.run_command_simple(
                ["talosctl", "health",
                 f"--nodes={self.master_node}",
                 f"--endpoints={self.master_node}"],
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
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_install_argocd(self, step_id: int) -> bool:
        """Step 7: Install ArgoCD."""
        await self.log(step_id, "info", "Running ArgoCD install script...")

        result = await self.process_manager.run_command(
            ["bash", "install.sh"],
            cwd=self.argocd_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_deploy_infrastructure(self, step_id: int) -> bool:
        """Step 8: Deploy infrastructure stack."""
        await self.log(step_id, "info", "Running deploy-ingress-stack.sh...")

        result = await self.process_manager.run_command(
            ["bash", "deploy-ingress-stack.sh"],
            cwd=self.projects_dir,
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_argocd_self_management(self, step_id: int) -> bool:
        """Step 9: Enable ArgoCD self-management."""
        await self.log(step_id, "info", "Enabling ArgoCD self-management...")

        app_yaml = self.projects_dir / "argocd" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=lambda line: self.log(step_id, "info", line)
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
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_deploy_faraday(self, step_id: int) -> bool:
        """Step 11: Deploy Faraday."""
        await self.log(step_id, "info", "Deploying Faraday...")

        app_yaml = self.projects_dir / "faraday" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_deploy_metasploit(self, step_id: int) -> bool:
        """Step 12: Deploy Metasploit."""
        await self.log(step_id, "info", "Deploying Metasploit...")

        app_yaml = self.projects_dir / "metasploit" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=lambda line: self.log(step_id, "info", line)
        )

        return result.success

    async def _step_deploy_threat_dragon(self, step_id: int) -> bool:
        """Step 13: Deploy Threat Dragon."""
        await self.log(step_id, "info", "Deploying Threat Dragon...")

        app_yaml = self.projects_dir / "threat-dragon" / "application.yaml"
        result = await self.process_manager.run_command(
            ["kubectl", "apply", "-f", str(app_yaml)],
            on_output=lambda line: self.log(step_id, "info", line)
        )

        # Wait for applications to sync
        await self.log(step_id, "info", "Waiting for applications to sync...")
        await asyncio.sleep(30)

        # Log deployment summary
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "==========================================")
        await self.log(step_id, "info", "Deployment complete!")
        await self.log(step_id, "info", "==========================================")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Default Credentials (CHANGE IN PRODUCTION!):")
        await self.log(step_id, "info", "  - ArgoCD:     admin / admin")
        await self.log(step_id, "info", "  - OpenVAS:    admin / admin")
        await self.log(step_id, "info", "  - Faraday:    faraday / admin")
        await self.log(step_id, "info", "  - Traefik/Longhorn: Uses basic-auth-secret")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Access services at:")
        await self.log(step_id, "info", "  - ArgoCD:        https://argocd.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Traefik:       https://traefik.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Longhorn:      https://longhorn.knowledgeondemand.net")
        await self.log(step_id, "info", "  - OpenVAS:       https://openvas.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Faraday:       https://faraday.knowledgeondemand.net")
        await self.log(step_id, "info", "  - Threat Dragon: https://threatdragon.knowledgeondemand.net")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Metasploit access (CLI only - no web UI):")
        await self.log(step_id, "info", "  kubectl exec -it -n metasploit deployment/metasploit -c metasploit -- ./msfconsole")
        await self.log(step_id, "info", "")
        await self.log(step_id, "info", "Note: OpenVAS feed sync takes 30-60 minutes on first deployment.")
        await self.log(step_id, "info", "==========================================")

        return result.success


# Global deployment service instance
_deployment_service: Optional[DeploymentService] = None


def get_deployment_service() -> DeploymentService:
    """Get or create deployment service instance."""
    global _deployment_service
    if _deployment_service is None:
        _deployment_service = DeploymentService()
    return _deployment_service
