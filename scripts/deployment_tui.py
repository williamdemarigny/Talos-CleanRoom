#!/usr/bin/env python3
"""
Talos CleanRoom Deployment TUI
A text-based user interface for deploying Talos Kubernetes clusters.
Matches functionality of DeployCluster.sh
"""

import subprocess
import os
import sys
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.text import Text
    from rich.markup import escape as rich_escape
except ImportError:
    print("Error: 'rich' library is required. Install with: pip install rich")
    sys.exit(1)

# Configuration
MASTER_NODE = "talos-CleanRoom-master-01.knowledgeondemand.net"
HEALTH_CHECK_RETRIES = 30
HEALTH_CHECK_INTERVAL = 10
DEPENDENCIES = ["terraform", "talhelper", "talosctl", "sops", "jq", "curl", "kubectl", "git"]

console = Console()


class DeploymentTUI:
    def __init__(self):
        self.repo_root: Optional[Path] = None
        self.current_step = 0
        self.total_steps = 8
        self.failed = False

    def get_repo_root(self) -> Optional[Path]:
        """Get the git repository root directory."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True
            )
            return Path(result.stdout.strip())
        except subprocess.CalledProcessError:
            return None

    def command_exists(self, cmd: str) -> Tuple[bool, str]:
        """Check if a command exists in PATH."""
        path = shutil.which(cmd)
        return (path is not None, path or "not found")

    def backup_if_exists(self, file_path: Path) -> bool:
        """Backup a file if it exists. Returns True if backup was made."""
        if file_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = file_path.with_suffix(f"{file_path.suffix}.backup_{timestamp}")
            console.print(f"  [yellow]Backing up existing file: {rich_escape(file_path.name)} -> {rich_escape(backup_path.name)}[/yellow]")
            shutil.move(str(file_path), str(backup_path))
            return True
        return False

    def backup_dir_if_exists(self, dir_path: Path) -> bool:
        """Backup a directory if it exists. Returns True if backup was made."""
        if dir_path.exists() and dir_path.is_dir():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = dir_path.with_name(f"{dir_path.name}.backup_{timestamp}")
            console.print(f"  [yellow]Backing up existing directory: {rich_escape(dir_path.name)} -> {rich_escape(backup_path.name)}[/yellow]")
            shutil.move(str(dir_path), str(backup_path))
            return True
        return False

    def run_command(self, cmd: list, cwd: Optional[Path] = None,
                    env: Optional[dict] = None, stream_output: bool = True,
                    auto_confirm: bool = True) -> Tuple[bool, str]:
        """Run a command and optionally stream output.

        Args:
            cmd: Command and arguments to run
            cwd: Working directory
            env: Environment variables to add
            stream_output: Whether to stream output to console
            auto_confirm: If True, automatically respond 'y' to prompts
        """
        try:
            merged_env = os.environ.copy()
            if env:
                merged_env.update(env)

            # Prepare stdin - provide 'y' responses for auto-confirm, otherwise close stdin
            stdin_input = "y\n" * 10 if auto_confirm else None

            if stream_output:
                process = subprocess.Popen(
                    cmd, cwd=cwd, env=merged_env,
                    stdin=subprocess.PIPE if auto_confirm else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                output_lines = []
                if auto_confirm and process.stdin:
                    try:
                        process.stdin.write("y\n" * 10)
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass  # Command may not need input
                for line in iter(process.stdout.readline, ''):
                    line = line.rstrip()
                    if line:
                        output_lines.append(line)
                        console.print(f"  [dim]{rich_escape(line)}[/dim]")
                process.wait()
                return (process.returncode == 0, "\n".join(output_lines))
            else:
                result = subprocess.run(
                    cmd, cwd=cwd, env=merged_env,
                    input=stdin_input,
                    capture_output=True, text=True
                )
                return (result.returncode == 0, result.stdout + result.stderr)
        except Exception as e:
            return (False, str(e))

    def cleanup(self):
        """Perform cleanup on failure - terraform destroy."""
        console.print("\n[yellow]Performing cleanup...[/yellow]")
        if self.repo_root:
            tf_dir = self.repo_root / "terraform" / "cluster-create"
            if tf_dir.exists():
                console.print("[yellow]Running terraform destroy...[/yellow]")
                success, _ = self.run_command(
                    ["terraform", "destroy", "-auto-approve"],
                    cwd=tf_dir
                )
                if not success:
                    console.print("[red]Warning: terraform destroy failed[/red]")
            else:
                console.print("[yellow]Warning: Terraform directory not found for cleanup[/yellow]")
        else:
            console.print("[yellow]Warning: Could not determine repository root for cleanup[/yellow]")

    def print_header(self):
        """Print the deployment header."""
        header = Panel(
            Text("Talos CleanRoom Deployment", justify="center", style="bold cyan"),
            subtitle="Automated Kubernetes Cluster Deployment",
            border_style="cyan"
        )
        console.print(header)
        console.print()

    def print_step(self, step_num, description: str, status: str = "running"):
        """Print a step indicator."""
        icons = {
            "running": "[yellow]>[/yellow]",
            "success": "[green]OK[/green]",
            "failed": "[red]FAIL[/red]",
            "pending": "[dim]o[/dim]"
        }
        icon = icons.get(status, icons["pending"])
        if status == "running":
            console.print(f"{icon} Step {step_num}: [bold]{description}[/bold]")
        else:
            console.print(f"{icon} Step {step_num}: {description}")

    def step_0_validate_git(self) -> bool:
        """Step 0: Validate git repository."""
        self.print_step(0, "Validating git repository", "running")

        self.repo_root = self.get_repo_root()
        if not self.repo_root:
            console.print("  [red]Error: This script must be run from within the git repository.[/red]")
            self.print_step(0, "Validating git repository", "failed")
            return False

        console.print(f"  [green]Repository root: {rich_escape(str(self.repo_root))}[/green]")
        self.print_step(0, "Validating git repository", "success")
        return True

    def step_0_1_check_dependencies(self) -> bool:
        """Step 0.1: Check required dependencies."""
        self.print_step("0.1", "Checking dependencies", "running")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Dependency", style="cyan")
        table.add_column("Status")
        table.add_column("Path", style="dim")

        all_found = True
        for dep in DEPENDENCIES:
            found, path = self.command_exists(dep)
            if found:
                table.add_row(dep, "[green]Found[/green]", rich_escape(path))
            else:
                table.add_row(dep, "[red]Missing[/red]", "-")
                all_found = False

        console.print(table)

        if not all_found:
            console.print("  [red]Error: Missing required dependencies.[/red]")
            self.print_step("0.1", "Checking dependencies", "failed")
            return False

        self.print_step("0.1", "Checking dependencies", "success")
        return True

    def step_1_terraform(self) -> bool:
        """Step 1: Terraform Deployment."""
        self.print_step(1, "Terraform Deployment", "running")

        tf_dir = self.repo_root / "terraform" / "cluster-create"

        if not tf_dir.exists():
            console.print(f"  [red]Error: Terraform directory not found: {rich_escape(str(tf_dir))}[/red]")
            self.print_step(1, "Terraform Deployment", "failed")
            return False

        # Terraform init
        console.print("  [cyan]Running terraform init...[/cyan]")
        success, _ = self.run_command(["terraform", "init"], cwd=tf_dir)
        if not success:
            console.print("  [red]Error: Terraform init failed[/red]")
            self.print_step(1, "Terraform Deployment", "failed")
            return False

        # Terraform plan
        console.print("  [cyan]Running terraform plan...[/cyan]")
        success, _ = self.run_command(["terraform", "plan", "-out=.tfplan"], cwd=tf_dir)
        if not success:
            console.print("  [red]Error: Terraform plan failed[/red]")
            self.print_step(1, "Terraform Deployment", "failed")
            return False

        # Terraform apply
        console.print("  [cyan]Running terraform apply...[/cyan]")
        success, _ = self.run_command(["terraform", "apply", ".tfplan"], cwd=tf_dir)
        if not success:
            console.print("  [red]Error: Terraform apply failed[/red]")
            self.print_step(1, "Terraform Deployment", "failed")
            return False

        self.print_step(1, "Terraform Deployment", "success")
        return True

    def step_2_talos_config_generation(self) -> bool:
        """Step 2: Talos Configuration Generation."""
        self.print_step(2, "Talos Configuration Generation", "running")

        talos_dir = self.repo_root / "cluster"

        # Run tfvars-to-talos-env.sh
        console.print("  [cyan]Running tfvars-to-talos-env.sh...[/cyan]")
        script_path = self.repo_root / "scripts" / "tfvars-to-talos-env.sh"
        if not script_path.exists():
            console.print(f"  [red]Error: Script not found: {rich_escape(str(script_path))}[/red]")
            self.print_step(2, "Talos Configuration Generation", "failed")
            return False

        success, _ = self.run_command(["bash", str(script_path), "--backup"], cwd=self.repo_root)
        if not success:
            console.print("  [red]Error: tfvars-to-talos-env.sh failed[/red]")
            self.print_step(2, "Talos Configuration Generation", "failed")
            return False

        # Set SOPS_AGE_KEY_FILE
        sops_key_file = os.environ.get("SOPS_AGE_KEY_FILE",
                                        os.path.expanduser("~/.config/sops/age/keys.txt"))
        env = {"SOPS_AGE_KEY_FILE": sops_key_file}

        # Backup existing secret file if it exists
        secret_file = talos_dir / "talsecret.sops.yaml"
        self.backup_if_exists(secret_file)

        # Generate Talos secret
        console.print("  [cyan]Generating Talos secret...[/cyan]")
        success, output = self.run_command(
            ["talhelper", "gensecret"], cwd=talos_dir, stream_output=False, auto_confirm=True
        )
        if not success:
            console.print("  [red]Error: Failed to generate Talos secret[/red]")
            self.print_step(2, "Talos Configuration Generation", "failed")
            return False

        # Write secret to file
        secret_file.write_text(output)

        # Encrypt with SOPS
        console.print("  [cyan]Encrypting secret with SOPS...[/cyan]")
        success, _ = self.run_command(
            ["sops", "-e", "-i", "talsecret.sops.yaml"],
            cwd=talos_dir, env=env, auto_confirm=True
        )
        if not success:
            console.print("  [red]Error: Failed to encrypt Talos secret[/red]")
            self.print_step(2, "Talos Configuration Generation", "failed")
            return False

        # Backup existing clusterconfig directory if it exists
        clusterconfig_dir = talos_dir / "clusterconfig"
        self.backup_dir_if_exists(clusterconfig_dir)

        # Generate Talos config
        console.print("  [cyan]Generating Talos config...[/cyan]")
        success, _ = self.run_command(
            ["talhelper", "genconfig", "--env-file", "talenv.yaml"],
            cwd=talos_dir, env=env, auto_confirm=True
        )
        if not success:
            console.print("  [red]Error: Failed to generate Talos config[/red]")
            self.print_step(2, "Talos Configuration Generation", "failed")
            return False

        self.print_step(2, "Talos Configuration Generation", "success")
        return True

    def step_3_apply_talos_configs(self) -> bool:
        """Step 3: Apply Talos Configurations."""
        self.print_step(3, "Apply Talos Configurations", "running")

        talos_dir = self.repo_root / "cluster"
        talosconfig = talos_dir / "clusterconfig" / "talosconfig"

        env = {"TALOSCONFIG": str(talosconfig)}

        console.print("  [cyan]Running apply-configs.sh --bootstrap...[/cyan]")
        success, _ = self.run_command(
            ["bash", "apply-configs.sh", "--bootstrap"],
            cwd=talos_dir, env=env
        )
        if not success:
            console.print("  [red]Error: Failed to apply Talos configurations[/red]")
            self.print_step(3, "Apply Talos Configurations", "failed")
            return False

        self.print_step(3, "Apply Talos Configurations", "success")
        return True

    def step_4_verify_cluster_health(self) -> bool:
        """Step 4: Verify Cluster Health."""
        self.print_step(4, "Verify Cluster Health", "running")

        talos_dir = self.repo_root / "cluster"
        talosconfig = talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        max_wait = HEALTH_CHECK_RETRIES * HEALTH_CHECK_INTERVAL
        console.print(f"  [cyan]Waiting for cluster health (max wait: {max_wait} seconds)...[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Health check", total=HEALTH_CHECK_RETRIES)

            for i in range(1, HEALTH_CHECK_RETRIES + 1):
                success, _ = self.run_command(
                    ["talosctl", "health", f"--nodes={MASTER_NODE}"],
                    env=env, stream_output=False
                )

                if success:
                    progress.update(task, completed=HEALTH_CHECK_RETRIES,
                                   description="[green]Cluster is healthy![/green]")
                    self.print_step(4, "Verify Cluster Health", "success")
                    return True

                progress.update(task, completed=i,
                               description=f"Retrying ({i}/{HEALTH_CHECK_RETRIES})...")
                time.sleep(HEALTH_CHECK_INTERVAL)

        console.print("  [red]Error: Cluster failed to become healthy within the allowed time.[/red]")
        self.print_step(4, "Verify Cluster Health", "failed")
        return False

    def step_5_get_kubeconfig(self) -> bool:
        """Step 5: Get kubeconfig."""
        self.print_step(5, "Get kubeconfig", "running")

        talos_dir = self.repo_root / "cluster"
        talosconfig = talos_dir / "clusterconfig" / "talosconfig"
        env = {"TALOSCONFIG": str(talosconfig)}

        kubeconfig_path = Path.home() / ".kube" / "config"

        # Ensure .kube directory exists
        kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)

        # Backup existing kubeconfig if it exists
        self.backup_if_exists(kubeconfig_path)

        console.print(f"  [cyan]Retrieving kubeconfig to {rich_escape(str(kubeconfig_path))}...[/cyan]")
        success, _ = self.run_command(
            ["talosctl", "kubeconfig", f"--nodes={MASTER_NODE}", str(kubeconfig_path)],
            env=env
        )
        if not success:
            console.print("  [red]Error: Failed to retrieve kubeconfig[/red]")
            self.print_step(5, "Get kubeconfig", "failed")
            return False

        self.print_step(5, "Get kubeconfig", "success")
        return True

    def step_6_install_argocd(self) -> bool:
        """Step 6: Install ArgoCD."""
        self.print_step(6, "Install ArgoCD", "running")

        argocd_dir = self.repo_root / "apps" / "argocd"

        console.print("  [cyan]Running ArgoCD install script...[/cyan]")
        success, _ = self.run_command(
            ["bash", "install.sh"],
            cwd=argocd_dir
        )
        if not success:
            console.print("  [red]Error: Failed to install ArgoCD[/red]")
            self.print_step(6, "Install ArgoCD", "failed")
            return False

        # Get ArgoCD password
        console.print("  [cyan]Retrieving ArgoCD admin password...[/cyan]")
        success, output = self.run_command(
            ["kubectl", "-n", "argocd", "get", "secret", "argocd-initial-admin-secret",
             "-o", "jsonpath={.data.password}"],
            stream_output=False
        )
        if success and output:
            import base64
            try:
                password = base64.b64decode(output).decode('utf-8')
                console.print(Panel(
                    f"[bold green]ArgoCD Admin Password:[/bold green] {rich_escape(password)}",
                    title="ArgoCD Credentials",
                    border_style="green"
                ))
            except Exception:
                console.print("  [yellow]Warning: Could not decode ArgoCD password[/yellow]")

        self.print_step(6, "Install ArgoCD", "success")
        return True

    def step_7_deploy_infrastructure(self) -> bool:
        """Step 7: Deploy Infrastructure Stack."""
        self.print_step(7, "Deploy Infrastructure Stack", "running")

        projects_dir = self.repo_root / "apps"

        console.print("  [cyan]Running deploy-ingress-stack.sh...[/cyan]")
        success, _ = self.run_command(
            ["bash", "deploy-ingress-stack.sh"],
            cwd=projects_dir
        )
        if not success:
            console.print("  [red]Error: Failed to deploy infrastructure stack[/red]")
            self.print_step(7, "Deploy Infrastructure Stack", "failed")
            return False

        self.print_step(7, "Deploy Infrastructure Stack", "success")
        return True

    def run(self) -> bool:
        """Run the complete deployment process."""
        self.print_header()

        steps = [
            (self.step_0_validate_git, "Validate git repository"),
            (self.step_0_1_check_dependencies, "Check dependencies"),
            (self.step_1_terraform, "Terraform Deployment"),
            (self.step_2_talos_config_generation, "Talos Configuration Generation"),
            (self.step_3_apply_talos_configs, "Apply Talos Configurations"),
            (self.step_4_verify_cluster_health, "Verify Cluster Health"),
            (self.step_5_get_kubeconfig, "Get kubeconfig"),
            (self.step_6_install_argocd, "Install ArgoCD"),
            (self.step_7_deploy_infrastructure, "Deploy Infrastructure Stack"),
        ]

        for step_func, step_name in steps:
            console.print()
            if not step_func():
                self.failed = True
                console.print()
                console.print(Panel(
                    f"[bold red]Deployment failed at: {step_name}[/bold red]",
                    border_style="red"
                ))
                self.cleanup()
                return False

        console.print()
        console.print(Panel(
            "[bold green]Deployment complete![/bold green]",
            border_style="green"
        ))
        return True


def main():
    """Main entry point."""
    try:
        tui = DeploymentTUI()
        success = tui.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Deployment cancelled by user.[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {rich_escape(str(e))}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
