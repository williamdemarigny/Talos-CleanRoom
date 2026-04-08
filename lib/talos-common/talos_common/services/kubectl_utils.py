"""Kubernetes helper utilities for common kubectl operations.

Provides the KubernetesHelper class that encapsulates frequently-used
kubectl command patterns (get pods, get secrets, exec, delete, etc.)
shared across scan_service, ioc_scan_service, and deployment_service.

All methods delegate to ProcessManager.run_command_simple() and return
the same ProcessResult objects used throughout the codebase.
"""

import asyncio
import base64 as b64
import re
from typing import Optional, List

from talos_common.services.process_manager import ProcessManager, ProcessResult

# Kubernetes namespace names: lowercase alphanumeric + hyphens, 1-63 chars,
# must start/end with alphanumeric.  RFC 1123 label.
_NAMESPACE_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$')


class KubernetesHelper:
    """Helper class for common kubectl operations.

    Wraps repetitive kubectl command construction patterns into reusable
    methods. Accepts a ProcessManager instance in its constructor — the
    same process_manager used by the service classes.

    Example usage::

        k8s = KubernetesHelper(process_manager)
        pod = await k8s.get_pod_name("faraday", "app.kubernetes.io/name=faraday")
        if pod:
            result = await k8s.exec_in_pod("faraday", pod, ["ls", "/tmp"])
    """

    def __init__(self, process_manager: ProcessManager):
        self.process_manager = process_manager

    async def check_connectivity(self, timeout: float = 10) -> bool:
        """Check if kubectl can connect to the Kubernetes cluster.

        Runs ``kubectl get nodes`` which requires minimal RBAC permissions.

        Returns:
            True if the cluster is reachable, False otherwise.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "nodes", "--request-timeout=5s", "-o", "name"],
            timeout=timeout
        )
        return result.success

    async def get_pod_name(
        self,
        namespace: str,
        label_selector: str,
        timeout: float = 10
    ) -> Optional[str]:
        """Get the name of the first pod matching a label selector.

        Runs::

            kubectl get pods -n {namespace} -l {label_selector}
                -o jsonpath={.items[0].metadata.name}

        Args:
            namespace: Kubernetes namespace to search in.
            label_selector: Label selector (e.g. ``app.kubernetes.io/name=faraday``).
            timeout: Command timeout in seconds.

        Returns:
            The pod name string, or None if no pod was found or the
            command failed.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pods", "-n", namespace,
             "-l", label_selector,
             "-o", "jsonpath={.items[0].metadata.name}"],
            timeout=timeout
        )
        if result.success and result.output.strip():
            return result.output.strip()
        return None

    async def get_secret(
        self,
        namespace: str,
        secret_name: str,
        key: str,
        timeout: float = 10
    ) -> Optional[str]:
        """Get and base64-decode a value from a Kubernetes secret.

        Runs kubectl to retrieve the base64-encoded secret value via
        jsonpath, then decodes it.

        Args:
            namespace: Kubernetes namespace containing the secret.
            secret_name: Name of the Secret resource.
            key: The data key within the secret (e.g. ``admin-password``).
            timeout: Command timeout in seconds.

        Returns:
            The decoded secret value string, or None if the secret could
            not be retrieved or decoded.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "secret", secret_name, "-n", namespace,
             "-o", f"jsonpath={{.data.{key}}}"],
            timeout=timeout
        )

        if not result.success or not result.output.strip():
            return None

        password_b64 = result.output.strip()

        # Decode base64 in Python (avoids shell injection risk and subprocess overhead)
        try:
            decoded = b64.b64decode(password_b64).decode("utf-8").strip()
            return decoded if decoded else None
        except Exception:
            return None

    async def get_pod_phase(
        self,
        namespace: str,
        pod_name: str,
        timeout: float = 10
    ) -> Optional[str]:
        """Get the phase of a specific pod.

        Runs::

            kubectl get pod {pod_name} -n {namespace}
                -o jsonpath={.status.phase}

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod.
            timeout: Command timeout in seconds.

        Returns:
            The pod phase string (e.g. ``Running``, ``Succeeded``, ``Failed``,
            ``Pending``), or None if the command failed.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pod", pod_name, f"--namespace={namespace}",
             "-o", "jsonpath={.status.phase}"],
            timeout=timeout
        )
        if result.success:
            phase = result.output.strip()
            return phase if phase else None
        return None

    async def get_pod_termination_info(
        self,
        namespace: str,
        pod_name: str,
        timeout: float = 10
    ) -> Optional[dict]:
        """Get container termination details (exit code, reason, message).

        Queries the first container's last termination state. Useful for
        understanding why a pod exited with failure.

        Returns:
            Dict with keys ``exit_code``, ``reason``, ``message`` if
            termination info is available, else None.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pod", pod_name, f"--namespace={namespace}",
             "-o", "jsonpath={.status.containerStatuses[0].state.terminated}"],
            timeout=timeout
        )
        if result.success and result.output.strip():
            try:
                import json as _json
                info = _json.loads(result.output.strip())
                return {
                    "exit_code": info.get("exitCode"),
                    "reason": info.get("reason", ""),
                    "message": info.get("message", ""),
                }
            except (ValueError, KeyError):
                pass
        return None

    async def exec_in_pod(
        self,
        namespace: str,
        pod_name: str,
        command: List[str],
        container: Optional[str] = None,
        env: Optional[dict] = None,
        timeout: float = 30
    ) -> ProcessResult:
        """Execute a command inside a pod via kubectl exec.

        Builds the full ``kubectl exec`` command including optional
        container selection and environment variable injection via
        the ``env`` command prefix.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod (can include ``pod/`` prefix or not).
            command: Command and arguments to run inside the pod.
            container: Optional container name (``-c`` flag).
            env: Optional dict of environment variables to inject
                 via ``env KEY=VALUE ...`` prefix.
            timeout: Command timeout in seconds.

        Returns:
            ProcessResult from the kubectl exec command.
        """
        # Build base kubectl exec command
        cmd = ["kubectl", "exec", "-n", namespace]

        # Ensure pod name has the pod/ prefix for consistency
        if not pod_name.startswith("pod/") and not pod_name.startswith("deployment/"):
            cmd.append(f"pod/{pod_name}")
        else:
            cmd.append(pod_name)

        if container:
            cmd.extend(["-c", container])

        cmd.append("--")

        # If env vars are provided, use the `env` command to inject them
        if env:
            cmd.append("env")
            for key, value in env.items():
                cmd.append(f"{key}={value}")

        cmd.extend(command)

        return await self.process_manager.run_command_simple(cmd, timeout=timeout)

    async def delete_pod(
        self,
        namespace: str,
        pod_name: str,
        force: bool = True,
        timeout: float = 30
    ) -> ProcessResult:
        """Delete a pod, optionally with force and zero grace period.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod to delete.
            force: If True, adds ``--force --grace-period=0`` flags.
            timeout: Command timeout in seconds.

        Returns:
            ProcessResult from the kubectl delete command.
        """
        cmd = ["kubectl", "delete", "pod", pod_name,
               f"--namespace={namespace}", "--ignore-not-found"]

        if force:
            cmd.extend(["--grace-period=0", "--force"])

        return await self.process_manager.run_command_simple(cmd, timeout=timeout)

    async def create_pod_from_spec(
        self,
        namespace: str,
        pod_name: str,
        image: str,
        pod_override_json: str,
        timeout: float = 30
    ) -> ProcessResult:
        """Create a pod using kubectl run with JSON overrides.

        This matches the pattern used by ioc_scan_service for creating
        LOKI-RS scanner pods and scan_service for Nmap pods.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name for the new pod.
            image: Container image to use.
            pod_override_json: JSON string with pod spec overrides.
            timeout: Command timeout in seconds.

        Returns:
            ProcessResult from the kubectl run command.
        """
        return await self.process_manager.run_command_simple(
            ["kubectl", "run", pod_name,
             f"--image={image}",
             "--restart=Never",
             f"--namespace={namespace}",
             f"--overrides={pod_override_json}"],
            timeout=timeout
        )

    async def get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        timeout: float = 60
    ) -> ProcessResult:
        """Retrieve logs from a pod.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod.
            timeout: Command timeout in seconds.

        Returns:
            ProcessResult with the pod logs in output.
        """
        return await self.process_manager.run_command_simple(
            ["kubectl", "logs", pod_name, f"--namespace={namespace}"],
            timeout=timeout
        )

    async def ensure_namespace(
        self,
        namespace: str,
        privileged: bool = False,
        timeout: float = 15
    ) -> ProcessResult:
        """Ensure a namespace exists, optionally with privileged PodSecurity.

        Uses ``kubectl create namespace --dry-run=client -o yaml | kubectl apply``
        for idempotency. Optionally labels the namespace with
        ``pod-security.kubernetes.io/enforce=privileged``.

        Args:
            namespace: Namespace to create/ensure.
            privileged: If True, label the namespace as privileged.
            timeout: Command timeout in seconds.

        Returns:
            ProcessResult from the operation.

        Raises:
            ValueError: If ``namespace`` contains characters outside the
                allowed Kubernetes naming rules (RFC 1123 label).
        """
        if not _NAMESPACE_RE.match(namespace):
            raise ValueError(
                f"Invalid namespace name: {namespace!r}. "
                "Must match RFC 1123: lowercase alphanumeric or '-', 1-63 chars, "
                "start/end with alphanumeric."
            )
        if privileged:
            return await self.process_manager.run_command_simple(
                ["bash", "-c",
                 f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f - && "
                 f"kubectl label namespace {namespace} pod-security.kubernetes.io/enforce=privileged --overwrite"],
                timeout=timeout
            )
        else:
            return await self.process_manager.run_command_simple(
                ["bash", "-c",
                 f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f -"],
                timeout=timeout
            )

    async def wait_for_pod_phase(
        self,
        namespace: str,
        pod_name: str,
        target_phases: List[str],
        timeout_seconds: int = 300,
        poll_interval: int = 5
    ) -> Optional[str]:
        """Poll until a pod reaches one of the target phases.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod.
            target_phases: List of phase strings to wait for
                (e.g. ``["Succeeded", "Failed"]``).
            timeout_seconds: Maximum time to wait.
            poll_interval: Seconds between polls.

        Returns:
            The phase string when reached, or None if timed out.
        """
        max_polls = timeout_seconds // poll_interval
        for _ in range(max_polls):
            phase = await self.get_pod_phase(namespace, pod_name)
            if phase in target_phases:
                return phase
            if phase is None or phase == "":
                # Pod may have been deleted
                return phase
            await asyncio.sleep(poll_interval)
        return None

    async def get_pod_waiting_reason(
        self,
        namespace: str,
        pod_name: str,
        timeout: float = 10
    ) -> Optional[str]:
        """Get the waiting reason for a pod's first container.

        Useful for detecting ImagePullBackOff, ErrImagePull, etc.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod.
            timeout: Command timeout in seconds.

        Returns:
            The waiting reason string, or None.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pod", pod_name, f"--namespace={namespace}",
             "-o", "jsonpath={.status.containerStatuses[0].state.waiting.reason}"],
            timeout=timeout
        )
        if result.success and result.output.strip():
            return result.output.strip()
        return None
