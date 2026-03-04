"""Base service class with shared patterns for all service classes.

Provides the BaseServiceMixin with common functionality used across
DeploymentService, ScanService, and IocScanService:

- Structured logging with async callback support
- Poll-until-condition utility for waiting on async operations
- Kubernetes connectivity checking
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable, Awaitable, TypeVar, Any

from app.services.process_manager import ProcessManager
from app.services.kubectl_utils import KubernetesHelper

T = TypeVar("T")


class BaseServiceMixin:
    """Mixin providing shared service patterns.

    This mixin is designed to be used alongside ``@dataclass`` service
    classes. It provides common methods that all three services share.

    The mixin expects the following attributes to exist on the class:

    - ``process_manager``: A ProcessManager instance
    - ``logs``: A list to append log entries to

    Subclasses must implement ``_create_log_entry()`` to create the
    appropriate domain-specific log entry type.

    Example usage::

        @dataclass
        class MyService(BaseServiceMixin):
            process_manager: ProcessManager = field(default_factory=ProcessManager)
            logs: List[MyLogEntry] = field(default_factory=list)
            log_callback: Optional[Callable] = None

            def _create_log_entry(self, level, message, **kwargs):
                return MyLogEntry(timestamp=datetime.utcnow(), level=level, message=message)
    """

    def _get_k8s_helper(self) -> KubernetesHelper:
        """Get or create a KubernetesHelper instance.

        Lazily creates the helper on first access using the service's
        process_manager.

        Returns:
            A KubernetesHelper instance.
        """
        if not hasattr(self, "_k8s_helper") or self._k8s_helper is None:
            self._k8s_helper = KubernetesHelper(self.process_manager)
        return self._k8s_helper

    @property
    def k8s(self) -> KubernetesHelper:
        """Shortcut property for the KubernetesHelper instance."""
        return self._get_k8s_helper()

    async def _log_with_callback(
        self,
        entry: Any,
        callback: Optional[Callable] = None
    ) -> None:
        """Append a log entry and invoke the callback if set.

        The callback invocation is wrapped in a try/except so that
        broadcast failures (e.g., disconnected WebSocket clients)
        never crash the service operation.

        Args:
            entry: The log entry to append and broadcast.
            callback: Optional async callback to invoke with the entry.
        """
        self.logs.append(entry)
        if callback:
            try:
                await callback(entry)
            except Exception:
                pass  # Don't let broadcast failures crash the operation

    async def check_cluster_connectivity(
        self,
        log_fn: Optional[Callable] = None
    ) -> bool:
        """Check if kubectl can connect to the Kubernetes cluster.

        Args:
            log_fn: Optional async function to call with error message
                if connectivity check fails.

        Returns:
            True if the cluster is reachable, False otherwise.
        """
        result = await self.process_manager.run_command_simple(
            ["kubectl", "cluster-info", "--request-timeout=5s"],
            timeout=10
        )
        if not result.success and log_fn:
            await log_fn("Cannot connect to Kubernetes cluster")
        return result.success

    @staticmethod
    async def poll_until(
        check_fn: Callable[[], Awaitable[T]],
        timeout: float,
        interval: float = 5,
        on_tick: Optional[Callable[[int, float], Awaitable[None]]] = None
    ) -> Optional[T]:
        """Poll an async check function until it returns a truthy value.

        Repeatedly calls ``check_fn()`` at the specified interval until
        it returns a truthy value or the timeout expires.

        Args:
            check_fn: Async function that returns a value. Polling stops
                when this returns a truthy value.
            timeout: Maximum time to poll in seconds.
            interval: Seconds between poll attempts.
            on_tick: Optional async callback called on each tick with
                ``(attempt_number, elapsed_seconds)``. Useful for
                progress logging.

        Returns:
            The truthy value from ``check_fn``, or None if timed out.
        """
        max_attempts = int(timeout / interval)
        for attempt in range(max_attempts):
            result = await check_fn()
            if result:
                return result

            if on_tick:
                elapsed = (attempt + 1) * interval
                await on_tick(attempt + 1, elapsed)

            await asyncio.sleep(interval)

        return None
