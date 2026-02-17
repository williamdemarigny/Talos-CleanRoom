"""Configuration service for reading/writing cluster configuration files.

This module provides the ConfigService class for managing Talos cluster
configuration files including Terraform tfvars and Talos YAML configs.
"""

import yaml
from pathlib import Path
from typing import Dict, Any
import hcl2

from app.config import get_settings
from app.models.config import ConfigValidationResult


class ConfigService:
    """Service for managing cluster configuration files."""

    def __init__(self):
        settings = get_settings()
        self.repo_root = settings.repo_root

    @property
    def terraform_dir(self) -> Path:
        """Get Terraform directory path."""
        return self.repo_root / "Resources" / "IAC-DNS" / "terraform" / "talos-cluster-create"

    @property
    def talos_dir(self) -> Path:
        """Get Talos configuration directory path."""
        return self.repo_root / "Resources" / "IAC-DNS" / "talos"

    @property
    def tfvars_path(self) -> Path:
        """Get cluster.auto.tfvars path."""
        return self.terraform_dir / "cluster.auto.tfvars"

    @property
    def talenv_path(self) -> Path:
        """Get talenv.yaml path."""
        return self.talos_dir / "talenv.yaml"

    @property
    def talconfig_path(self) -> Path:
        """Get talconfig.yaml path."""
        return self.talos_dir / "talconfig.yaml"

    async def get_terraform_config(self) -> Dict[str, Any]:
        """Read and parse cluster.auto.tfvars.

        Returns:
            Dict containing either:
            - {"success": True, "config": parsed_dict, "raw": raw_content}
            - {"success": False, "error": error_message}
        """
        if not self.tfvars_path.exists():
            return {"success": False, "error": f"File not found: {self.tfvars_path}"}

        try:
            with open(self.tfvars_path, 'r') as f:
                content = f.read()
                # Parse HCL2 format
                parsed = hcl2.loads(content)
                return {"success": True, "config": parsed, "raw": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_terraform_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update cluster.auto.tfvars with new configuration."""
        if not self.tfvars_path.exists():
            return {"success": False, "error": f"File not found: {self.tfvars_path}"}

        try:
            # Create backup
            backup_path = self.tfvars_path.with_suffix('.tfvars.backup')
            with open(self.tfvars_path, 'r') as f:
                backup_content = f.read()
            with open(backup_path, 'w') as f:
                f.write(backup_content)

            # Generate new tfvars content
            new_content = self._generate_tfvars(config)

            with open(self.tfvars_path, 'w') as f:
                f.write(new_content)

            return {"success": True, "backup": str(backup_path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_tfvars(self, config: Dict[str, Any]) -> str:
        """Generate tfvars content from config dict."""
        lines = []

        # Handle nodes list
        if 'nodes' in config:
            lines.append("nodes = [")
            for node in config['nodes']:
                lines.append("  {")
                for key, value in node.items():
                    if isinstance(value, str):
                        lines.append(f'    {key} = "{value}"')
                    elif isinstance(value, list):
                        items = ', '.join(f'"{v}"' for v in value)
                        lines.append(f'    {key} = [{items}]')
                    else:
                        lines.append(f'    {key} = {value}')
                lines.append("  },")
            lines.append("]")
            lines.append("")

        # Handle simple key-value pairs
        for key, value in config.items():
            if key == 'nodes':
                continue
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f'{key} = {str(value).lower()}')
            elif isinstance(value, (int, float)):
                lines.append(f'{key} = {value}')
            elif isinstance(value, list):
                items = ', '.join(f'"{v}"' if isinstance(v, str) else str(v) for v in value)
                lines.append(f'{key} = [{items}]')
            lines.append("")

        return '\n'.join(lines)

    async def get_talos_env(self) -> Dict[str, Any]:
        """Read and parse talenv.yaml.

        Returns:
            Dict containing either:
            - {"success": True, "config": parsed_content}
            - {"success": False, "error": error_message}
        """
        if not self.talenv_path.exists():
            return {"success": False, "error": f"File not found: {self.talenv_path}"}

        try:
            with open(self.talenv_path, 'r') as f:
                content = yaml.safe_load(f)
                return {"success": True, "config": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_talos_config(self) -> Dict[str, Any]:
        """Read and parse talconfig.yaml.

        Returns:
            Dict containing either:
            - {"success": True, "config": parsed_content}
            - {"success": False, "error": error_message}
        """
        if not self.talconfig_path.exists():
            return {"success": False, "error": f"File not found: {self.talconfig_path}"}

        try:
            with open(self.talconfig_path, 'r') as f:
                content = yaml.safe_load(f)
                return {"success": True, "config": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def validate_config(self) -> ConfigValidationResult:
        """Validate all configuration files.

        Checks that required files exist and contain valid configuration.

        Returns:
            ConfigValidationResult with validation status, errors, and warnings.
        """
        errors = []
        warnings = []

        # Check tfvars
        tf_result = await self.get_terraform_config()
        if not tf_result.get("success"):
            errors.append(f"Terraform config: {tf_result.get('error', 'Unknown error')}")
        else:
            config = tf_result.get("config", {})
            if not config.get("nodes"):
                errors.append("No nodes defined in Terraform config")

        # Check talenv.yaml
        env_result = await self.get_talos_env()
        if not env_result.get("success"):
            warnings.append(f"Talos env: {env_result.get('error', 'Unknown error')} (will be regenerated)")

        # Check talconfig.yaml
        tc_result = await self.get_talos_config()
        if not tc_result.get("success"):
            warnings.append(f"Talos config: {tc_result.get('error', 'Unknown error')} (will be regenerated)")

        return ConfigValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    async def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration in a single response."""
        terraform = await self.get_terraform_config()
        talos_env = await self.get_talos_env()
        talos_config = await self.get_talos_config()
        validation = await self.validate_config()

        return {
            "terraform": terraform,
            "talos_env": talos_env,
            "talos_config": talos_config,
            "validation": validation.model_dump()
        }
