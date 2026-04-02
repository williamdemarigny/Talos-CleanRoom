"""Vulhub target service — manages K8s-based vulnerable environment lifecycle.

Handles deployment, destruction, TTL management, and cleanup of ephemeral
Vulhub vulnerable environments deployed as K8s workloads in isolated namespaces.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select, and_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import engine as db_engine
from app.db.models import VulhubTarget
from app.services.vulhub_catalog import VULHUB_CATALOG, TIER_CONFIG
from talos_common.services.process_manager import ProcessManager

logger = logging.getLogger(__name__)

# Active statuses (not destroyed/error)
_ACTIVE_STATUSES = ("deploying", "running", "stopping")

# Advisory lock ID for serializing target allocation (PostgreSQL pg_advisory_lock)
_ALLOCATION_LOCK_ID = 839272

# Maximum deploy log entries kept per target (in-memory)
_MAX_DEPLOY_LOG_ENTRIES = 200


def _get_session_factory():
    """Get the async session factory, raising if DB not initialized."""
    factory = db_engine.get_session_factory()
    if factory is None:
        raise VulhubTargetError("Database not initialized.")
    return factory


class VulhubTargetError(Exception):
    """Raised for Vulhub target operation failures."""
    pass


class VulhubTargetService:
    """Manages Vulhub vulnerable environment lifecycle via kubectl."""

    def __init__(self):
        self._settings = get_settings()
        self._process_manager = ProcessManager()
        # In-memory deploy log buffer: target_id → list of log dicts
        self._deploy_logs: dict[int, list[dict]] = defaultdict(list)

    @property
    def enabled(self) -> bool:
        return self._settings.target_lab_enabled

    async def close(self):
        """Shutdown cleanup — cancel any running processes."""
        if self._process_manager.is_running:
            await self._process_manager.cancel()

    # ── Deploy logs ──────────────────────────────────────────────

    def _log_deploy(self, target_id: int, step: str, level: str, message: str):
        """Append a log entry to the in-memory deploy log buffer.

        Also forwards to the Python logger so it appears in container stdout.
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "step": step,
            "level": level,
            "message": message,
        }
        logs = self._deploy_logs[target_id]
        logs.append(entry)
        # Trim to prevent unbounded growth
        if len(logs) > _MAX_DEPLOY_LOG_ENTRIES:
            self._deploy_logs[target_id] = logs[-_MAX_DEPLOY_LOG_ENTRIES:]
        # Mirror to Python logger
        log_fn = getattr(logger, level, logger.info)
        log_fn("[target %d / %s] %s", target_id, step, message)

    def get_deploy_logs(self, target_id: int, offset: int = 0) -> list[dict]:
        """Return deploy log entries for a target, starting from offset."""
        logs = self._deploy_logs.get(target_id, [])
        return logs[offset:]

    def _clear_deploy_logs(self, target_id: int):
        """Remove deploy logs for a target (called on destroy/cleanup)."""
        self._deploy_logs.pop(target_id, None)

    async def _fetch_k8s_diagnostics(self, namespace: str) -> str:
        """Fetch K8s events and pod status for a namespace to diagnose failures."""
        diag_lines = []

        # Get pod statuses
        pod_result = await self._process_manager.run_command_simple(
            ["kubectl", "get", "pods", "-n", namespace,
             "-o", "jsonpath={range .items[*]}{.metadata.name}{'\\t'}{.status.phase}{'\\t'}"
             "{range .status.containerStatuses[*]}{.state}{end}{'\\n'}{end}"],
            timeout=15,
        )
        if pod_result.success and pod_result.output.strip():
            diag_lines.append("Pod statuses:")
            for line in pod_result.output.strip().splitlines():
                diag_lines.append(f"  {line}")

        # Get recent events (sorted by last timestamp)
        event_result = await self._process_manager.run_command_simple(
            ["kubectl", "get", "events", "-n", namespace,
             "--sort-by=.lastTimestamp",
             "-o", "custom-columns=TYPE:.type,REASON:.reason,MESSAGE:.message",
             "--no-headers"],
            timeout=15,
        )
        if event_result.success and event_result.output.strip():
            diag_lines.append("K8s events:")
            for line in event_result.output.strip().splitlines()[-15:]:
                diag_lines.append(f"  {line}")

        return "\n".join(diag_lines) if diag_lines else "No diagnostic info available."

    # ── Catalog ───────────────────────────────────────────────────

    def get_catalog(self, category: Optional[str] = None) -> list[dict]:
        """Return catalog entries, optionally filtered by category.

        Returns a list of dicts with env_id included in each entry.
        """
        result = []
        for env_id, entry in VULHUB_CATALOG.items():
            if category is not None and entry["category"] != category:
                continue
            result.append({"env_id": env_id, **entry})
        return result

    def get_catalog_entry(self, env_id: str) -> Optional[dict]:
        """Return a single catalog entry with env_id included, or None."""
        entry = VULHUB_CATALOG.get(env_id)
        if entry is None:
            return None
        return {"env_id": env_id, **entry}

    # ── Capacity ──────────────────────────────────────────────────

    async def get_capacity(self) -> dict:
        """Return current capacity info."""
        factory = _get_session_factory()
        async with factory() as session:
            active = await self._get_active_targets(session)
        max_concurrent = self._settings.vulhub_target_max_concurrent
        return {
            "used": len(active),
            "max": max_concurrent,
            "available": max(0, max_concurrent - len(active)),
        }

    async def _get_active_targets(self, session: AsyncSession) -> list[VulhubTarget]:
        result = await session.execute(
            select(VulhubTarget).where(VulhubTarget.status.in_(_ACTIVE_STATUSES))
        )
        return list(result.scalars().all())

    # ── Deploy ────────────────────────────────────────────────────

    async def deploy_target(self, env_id: str, username: str = "admin") -> dict:
        """Deploy a new Vulhub vulnerable environment.

        Uses a PostgreSQL advisory lock to prevent race conditions in
        concurrent namespace allocation.

        Args:
            env_id: Catalog key (e.g. "log4shell").
            username: User initiating the deployment.

        Returns:
            Dict with target info including namespace and service endpoint.

        Raises:
            VulhubTargetError: If catalog entry not found, capacity exceeded,
                or deployment fails.
        """
        if not self.enabled:
            raise VulhubTargetError("Target Lab is not enabled.")

        # Validate catalog entry
        catalog_entry = VULHUB_CATALOG.get(env_id)
        if not catalog_entry:
            raise VulhubTargetError(f"Unknown environment: {env_id}")

        settings = self._settings
        ns_suffix = uuid.uuid4().hex[:6]
        namespace = f"vulhub-{env_id}-{ns_suffix}"
        manifest_filename = catalog_entry["manifest"]
        manifest_path = Path(settings.vulhub_manifests_dir) / manifest_filename

        if not manifest_path.exists():
            raise VulhubTargetError(
                f"Manifest not found: {manifest_path}. "
                "Ensure the manifest is baked into the container image."
            )

        factory = _get_session_factory()
        async with factory() as session:
            # Acquire advisory lock to serialize allocation
            try:
                await asyncio.wait_for(
                    session.execute(text(f"SELECT pg_advisory_lock({_ALLOCATION_LOCK_ID})")),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                raise VulhubTargetError("Failed to acquire deployment lock (timeout). Try again.")

            try:
                active = await self._get_active_targets(session)

                # Check capacity
                if len(active) >= settings.vulhub_target_max_concurrent:
                    raise VulhubTargetError(
                        f"Maximum concurrent Vulhub targets reached ({settings.vulhub_target_max_concurrent}). "
                        "Destroy an existing target before deploying a new one."
                    )

                # Build service endpoint
                # Use the first service name from the manifest (deployment name)
                # Convention: deployment name = env_id with underscores as hyphens
                svc_name = env_id.replace("_", "-")
                primary_port = catalog_entry["ports"][0]
                service_endpoint = f"{svc_name}.{namespace}.svc.cluster.local:{primary_port}"

                now = datetime.utcnow()
                ttl_expires = now + timedelta(hours=settings.vulhub_target_ttl_hours)

                # Create DB record
                target = VulhubTarget(
                    env_id=env_id,
                    name=catalog_entry["name"],
                    namespace=namespace,
                    service_endpoint=service_endpoint,
                    cve_id=catalog_entry.get("cve"),
                    category=catalog_entry.get("category"),
                    status="deploying",
                    created_at=now,
                    ttl_expires_at=ttl_expires,
                    created_by=username,
                    ports_json=catalog_entry["ports"],
                )
                session.add(target)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    raise VulhubTargetError(
                        f"Namespace allocation conflict ({namespace}). Please retry."
                    )

                target_id = target.id

                # Create background task for the actual K8s deployment
                task = asyncio.create_task(
                    self._deploy_with_timeout(target_id, namespace, manifest_path, svc_name, env_id, catalog_entry)
                )
                task.add_done_callback(self._task_done_callback)
            finally:
                await session.execute(text(f"SELECT pg_advisory_unlock({_ALLOCATION_LOCK_ID})"))

        return {
            "id": target_id,
            "env_id": env_id,
            "name": catalog_entry["name"],
            "namespace": namespace,
            "service_endpoint": service_endpoint,
            "cve_id": catalog_entry.get("cve"),
            "category": catalog_entry.get("category"),
            "status": "deploying",
            "ttl_expires_at": ttl_expires.isoformat(),
            "ports": catalog_entry["ports"],
        }

    @staticmethod
    def _task_done_callback(task: asyncio.Task):
        """Log unhandled exceptions from background deploy tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background Vulhub deploy task failed: %s", exc)

    async def _deploy_with_timeout(self, target_id: int, namespace: str,
                                    manifest_path: Path, svc_name: str, env_id: str,
                                    catalog_entry: dict):
        """Wrap _deploy_target_k8s with a tier-based overall timeout."""
        tier = catalog_entry.get("tier", "tier2")
        tier_cfg = TIER_CONFIG.get(tier, TIER_CONFIG["tier2"])
        # Overall timeout = rollout timeout + 120s buffer for namespace/manifest/quota setup
        overall_timeout = tier_cfg["rollout_timeout"] + 120
        self._log_deploy(target_id, "init", "info",
                         f"Starting deployment of {env_id} (tier={tier}, timeout={overall_timeout}s)")
        try:
            await asyncio.wait_for(
                self._deploy_target_k8s(target_id, namespace, manifest_path, svc_name, env_id, catalog_entry),
                timeout=overall_timeout,
            )
        except asyncio.TimeoutError:
            self._log_deploy(target_id, "timeout", "error",
                             f"Deployment timed out after {overall_timeout}s")
            # Fetch K8s diagnostics before cleanup
            try:
                diag = await self._fetch_k8s_diagnostics(namespace)
                self._log_deploy(target_id, "diagnostics", "error", diag)
            except Exception:
                pass
            await self._update_status(target_id, "error", f"Deployment timed out after {overall_timeout}s")
            try:
                await self._delete_namespace(namespace)
            except Exception:
                pass

    async def _deploy_target_k8s(self, target_id: int, namespace: str,
                                  manifest_path: Path, svc_name: str, env_id: str,
                                  catalog_entry: dict):
        """Background task: create namespace, apply manifests, wait for rollout."""
        try:
            # Step 1: Create namespace with label
            self._log_deploy(target_id, "namespace", "info",
                             f"Creating namespace {namespace}")
            ns_json = json.dumps({
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": namespace,
                    "labels": {
                        "app.kubernetes.io/part-of": "vulhub-targets",
                        "app.kubernetes.io/managed-by": "scanning-console",
                        "vulhub.env-id": env_id,
                    },
                },
            })
            result = await self._kubectl_apply_stdin(ns_json)
            if not result.success:
                self._log_deploy(target_id, "namespace", "error",
                                 f"Failed to create namespace: {result.output}")
                raise VulhubTargetError(f"Failed to create namespace: {result.output}")
            self._log_deploy(target_id, "namespace", "info", "Namespace created")

            # Step 2: Apply the workload manifest (Deployment + Service)
            self._log_deploy(target_id, "manifest", "info",
                             f"Applying manifest {manifest_path.name} "
                             f"(images: {', '.join(catalog_entry.get('images', []))})")
            manifest_content = manifest_path.read_text()
            result = await self._kubectl_apply_stdin(manifest_content, namespace=namespace)
            if not result.success:
                self._log_deploy(target_id, "manifest", "error",
                                 f"Failed to apply manifest: {result.output}")
                raise VulhubTargetError(f"Failed to apply manifest: {result.output}")
            self._log_deploy(target_id, "manifest", "info", "Manifest applied")

            # Step 3: Apply NetworkPolicy (scanner ingress only, DNS-only egress)
            self._log_deploy(target_id, "network-policy", "info",
                             "Applying network isolation policy")
            netpol_json = self._build_network_policy_json()
            result = await self._kubectl_apply_stdin(netpol_json, namespace=namespace)
            if not result.success:
                self._log_deploy(target_id, "network-policy", "error",
                                 f"Failed to apply NetworkPolicy: {result.output}")
                raise VulhubTargetError(f"Failed to apply NetworkPolicy: {result.output}")
            self._log_deploy(target_id, "network-policy", "info", "NetworkPolicy applied")

            # Step 4: Apply ResourceQuota (tier-based)
            tier = catalog_entry.get("tier", "tier2")
            self._log_deploy(target_id, "resource-quota", "info",
                             f"Applying resource quota (tier={tier})")
            quota_json = self._build_resource_quota_json(tier=tier)
            result = await self._kubectl_apply_stdin(quota_json, namespace=namespace)
            if not result.success:
                self._log_deploy(target_id, "resource-quota", "error",
                                 f"Failed to apply ResourceQuota: {result.output}")
                raise VulhubTargetError(f"Failed to apply ResourceQuota: {result.output}")
            self._log_deploy(target_id, "resource-quota", "info", "ResourceQuota applied")

            # Step 5: Wait for rollout (tier-based timeout)
            tier_cfg = TIER_CONFIG.get(tier, TIER_CONFIG["tier2"])
            rollout_timeout = tier_cfg["rollout_timeout"]
            self._log_deploy(target_id, "rollout", "info",
                             f"Waiting for deployment/{svc_name} rollout "
                             f"(timeout={rollout_timeout}s)")
            result = await self._process_manager.run_command_simple(
                ["kubectl", "rollout", "status", f"deployment/{svc_name}",
                 "-n", namespace, f"--timeout={rollout_timeout}s"],
                timeout=rollout_timeout + 30,
            )
            if not result.success:
                self._log_deploy(target_id, "rollout", "warning",
                                 f"Rollout status check failed: {result.output}")
                # Don't fail hard — the deployment might have multiple deployments
                # or a different naming convention.  Check if pods are running.
                pod_check = await self._process_manager.run_command_simple(
                    ["kubectl", "get", "pods", "-n", namespace,
                     "-o", "jsonpath={.items[*].status.phase}"],
                    timeout=30,
                )
                if "Running" not in (pod_check.output or ""):
                    # Fetch K8s diagnostics to understand the failure
                    diag = await self._fetch_k8s_diagnostics(namespace)
                    self._log_deploy(target_id, "diagnostics", "error", diag)
                    raise VulhubTargetError(
                        f"Deployment did not reach Running state: {result.output}"
                    )
                self._log_deploy(target_id, "rollout", "info",
                                 "Pods are running (rollout check was inconclusive)")

            # Success
            self._log_deploy(target_id, "complete", "info",
                             f"Target {env_id} deployed successfully in {namespace}")
            await self._update_status(target_id, "running")

        except Exception as e:
            self._log_deploy(target_id, "error", "error", f"Deployment failed: {e}")
            # Fetch K8s diagnostics on any failure
            try:
                diag = await self._fetch_k8s_diagnostics(namespace)
                self._log_deploy(target_id, "diagnostics", "error", diag)
            except Exception:
                pass
            await self._update_status(target_id, "error", str(e))
            # Attempt cleanup
            self._log_deploy(target_id, "cleanup", "info",
                             f"Cleaning up namespace {namespace}")
            try:
                await self._delete_namespace(namespace)
            except Exception:
                pass

    def _build_network_policy_json(self) -> str:
        """Build the NetworkPolicy JSON for a Vulhub target namespace.

        Allows ingress from scanner namespaces only.
        Allows egress to kube-system DNS + intra-namespace only.
        """
        policy = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": "vulhub-target-isolation",
            },
            "spec": {
                "podSelector": {},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{
                    "from": [
                        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": ns}}}
                        for ns in ["nmap-scanner", "openvas", "metasploit", "scanning-console"]
                    ],
                }],
                "egress": [
                    # DNS resolution via kube-system
                    {
                        "to": [{
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"},
                            },
                        }],
                        "ports": [{"protocol": "UDP", "port": 53}],
                    },
                    # Intra-namespace (multi-container environments)
                    {
                        "to": [{"podSelector": {}}],
                    },
                ],
            },
        }
        return json.dumps(policy)

    def _build_resource_quota_json(self, tier: str = "tier2") -> str:
        """Build the ResourceQuota JSON for a Vulhub target namespace.

        Uses tier-based resource allocation.  Quota = per-container limit
        multiplied by max_pods for that tier (accommodates multi-container
        pods like Drupal + MySQL in tier3).
        """
        tier_cfg = TIER_CONFIG.get(tier, TIER_CONFIG["tier2"])
        max_pods = tier_cfg["max_pods"]
        cpu_limit_num = int(tier_cfg["cpu_limit"].rstrip("m"))
        mem_limit_num = int(tier_cfg["memory_limit"].rstrip("Mi"))
        quota = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {
                "name": "vulhub-target-quota",
            },
            "spec": {
                "hard": {
                    "pods": str(max_pods),
                    "requests.cpu": f"{cpu_limit_num * max_pods}m",
                    "requests.memory": f"{mem_limit_num * max_pods}Mi",
                    "limits.cpu": f"{cpu_limit_num * max_pods}m",
                    "limits.memory": f"{mem_limit_num * max_pods}Mi",
                },
            },
        }
        return json.dumps(quota)

    async def _kubectl_apply_stdin(self, yaml_content: str,
                                    namespace: Optional[str] = None):
        """Apply YAML via kubectl apply -f - with stdin."""
        cmd = ["kubectl", "apply", "-f", "-"]
        if namespace:
            cmd.extend(["-n", namespace])
        return await self._process_manager.run_command(
            cmd, stdin_data=yaml_content, timeout=60,
        )

    async def _delete_namespace(self, namespace: str):
        """Delete a K8s namespace (cascading cleanup)."""
        return await self._process_manager.run_command_simple(
            ["kubectl", "delete", "namespace", namespace,
             "--ignore-not-found=true", "--wait=false"],
            timeout=60,
        )

    # ── Destroy ───────────────────────────────────────────────────

    async def destroy_target(self, target_id: int, username: str = "admin") -> dict:
        """Destroy a Vulhub target environment.

        Deletes the K8s namespace (cascading cleanup of all resources)
        and updates the DB record.

        Args:
            target_id: Database ID of the target.
            username: User initiating destruction.

        Returns:
            Dict with target ID and status.

        Raises:
            VulhubTargetError: If target not found or not active.
        """
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(VulhubTarget).where(
                    and_(VulhubTarget.id == target_id, VulhubTarget.status.in_(_ACTIVE_STATUSES))
                )
            )
            target = result.scalar_one_or_none()
            if not target:
                raise VulhubTargetError(f"No active Vulhub target with ID {target_id}.")

            namespace = target.namespace
            target.status = "stopping"
            await session.commit()

        # Delete namespace (cascading cleanup)
        delete_result = await self._delete_namespace(namespace)
        if not delete_result.success:
            logger.warning(
                "Namespace deletion may have failed for %s: %s",
                namespace, delete_result.output,
            )

        await self._update_status(target_id, "destroyed")
        self._clear_deploy_logs(target_id)
        logger.info("Vulhub target %d (%s) destroyed by %s", target_id, namespace, username)
        return {"id": target_id, "status": "destroyed"}

    # ── TTL extension ─────────────────────────────────────────────

    async def extend_ttl(self, target_id: int, hours: int = 2) -> dict:
        """Extend the TTL of a running Vulhub target (max 12h from creation).

        Args:
            target_id: Database ID of the target.
            hours: Number of hours to extend from now.

        Returns:
            Dict with updated target info.

        Raises:
            VulhubTargetError: If target not found, not running, or
                extension exceeds maximum.
        """
        if hours < 1 or hours > 12:
            raise VulhubTargetError("TTL extension must be between 1 and 12 hours.")

        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(VulhubTarget).where(
                    and_(VulhubTarget.id == target_id, VulhubTarget.status == "running")
                )
            )
            target = result.scalar_one_or_none()
            if not target:
                raise VulhubTargetError(f"No running Vulhub target with ID {target_id}.")

            now = datetime.utcnow()
            new_ttl = now + timedelta(hours=hours)
            # Cap total lifetime at 12 hours from creation
            max_ttl = target.created_at + timedelta(hours=12)
            target.ttl_expires_at = min(new_ttl, max_ttl)
            await session.commit()
            return self._target_to_dict(target)

    # ── List & status ─────────────────────────────────────────────

    async def list_targets(self) -> list[dict]:
        """Return all active (non-destroyed) Vulhub targets."""
        factory = _get_session_factory()
        async with factory() as session:
            active = await self._get_active_targets(session)
            return [self._target_to_dict(t) for t in active]

    async def get_target(self, target_id: int) -> Optional[dict]:
        """Get a single Vulhub target by ID."""
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(VulhubTarget).where(VulhubTarget.id == target_id)
            )
            target = result.scalar_one_or_none()
            if not target:
                return None
            return self._target_to_dict(target)

    # ── TTL cleanup ───────────────────────────────────────────────

    async def cleanup_expired(self):
        """Destroy targets that have exceeded their TTL."""
        now = datetime.utcnow()
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(VulhubTarget).where(
                    and_(
                        VulhubTarget.status.in_(_ACTIVE_STATUSES),
                        VulhubTarget.ttl_expires_at <= now,
                    )
                )
            )
            expired = list(result.scalars().all())

        if not expired:
            return

        logger.info("TTL cleanup: destroying %d expired Vulhub target(s)", len(expired))
        for target in expired:
            try:
                await self.destroy_target(target.id, username="system-ttl")
            except Exception as e:
                logger.error("TTL cleanup failed for Vulhub target %d: %s", target.id, e)

    # ── Orphan reconciliation ─────────────────────────────────────

    async def reconcile_orphaned(self):
        """Detect and clean up orphaned targets.

        - Targets stuck in 'deploying' for >15 min: mark error, delete namespace
        - DB records whose namespace no longer exists: mark destroyed
        - Targets in 'error' for >10 min: delete namespace, mark destroyed
        """
        now = datetime.utcnow()
        deploy_cutoff = now - timedelta(minutes=15)
        error_cutoff = now - timedelta(minutes=10)
        factory = _get_session_factory()

        async with factory() as session:
            # Find stuck deployments
            result = await session.execute(
                select(VulhubTarget).where(
                    and_(
                        VulhubTarget.status == "deploying",
                        VulhubTarget.created_at <= deploy_cutoff,
                    )
                )
            )
            stuck_deploying = list(result.scalars().all())

            # Find stale error targets
            result2 = await session.execute(
                select(VulhubTarget).where(
                    and_(
                        VulhubTarget.status == "error",
                        VulhubTarget.created_at <= error_cutoff,
                    )
                )
            )
            stale_errors = list(result2.scalars().all())

            # Find running targets whose namespace no longer exists
            result3 = await session.execute(
                select(VulhubTarget).where(VulhubTarget.status == "running")
            )
            running = list(result3.scalars().all())

        # Handle stuck deployments
        for target in stuck_deploying:
            logger.warning(
                "Reconciling stuck Vulhub target %d (deploying since %s)",
                target.id, target.created_at,
            )
            await self._update_status(target.id, "error", "Deployment timed out (orphan reconciliation)")
            try:
                await self._delete_namespace(target.namespace)
            except Exception:
                pass

        # Handle stale error targets
        for target in stale_errors:
            logger.info("Cleaning up error Vulhub target %d, namespace %s", target.id, target.namespace)
            try:
                await self._delete_namespace(target.namespace)
            except Exception:
                pass
            await self._update_status(target.id, "destroyed")
            self._clear_deploy_logs(target.id)

        # Check running targets for orphaned namespaces
        for target in running:
            ns_exists = await self._namespace_exists(target.namespace)
            if not ns_exists:
                logger.warning(
                    "Vulhub target %d namespace %s no longer exists — marking destroyed",
                    target.id, target.namespace,
                )
                await self._update_status(target.id, "destroyed")

    async def _namespace_exists(self, namespace: str) -> bool:
        """Check if a K8s namespace exists."""
        result = await self._process_manager.run_command_simple(
            ["kubectl", "get", "namespace", namespace, "-o", "name"],
            timeout=10,
        )
        return result.success

    # ── Helpers ───────────────────────────────────────────────────

    async def _update_status(
        self, target_id: int, status: str, error: Optional[str] = None
    ):
        """Update target status in the database."""
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(VulhubTarget).where(VulhubTarget.id == target_id)
            )
            target = result.scalar_one_or_none()
            if target:
                target.status = status
                if error:
                    target.error_message = error
                if status == "destroyed":
                    target.destroyed_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    def _target_to_dict(target: VulhubTarget) -> dict:
        """Convert a VulhubTarget ORM object to a dict for API responses."""
        now = datetime.utcnow()
        ttl_expires = target.ttl_expires_at
        return {
            "id": target.id,
            "env_id": target.env_id,
            "name": target.name,
            "namespace": target.namespace,
            "service_endpoint": target.service_endpoint,
            "cve_id": target.cve_id,
            "category": target.category,
            "status": target.status,
            "created_at": target.created_at.isoformat() if target.created_at else None,
            "ttl_expires_at": ttl_expires.isoformat() if ttl_expires else None,
            "ttl_remaining_seconds": max(0, int((ttl_expires - now).total_seconds())) if ttl_expires else 0,
            "created_by": target.created_by,
            "error_message": target.error_message,
            "ports": target.ports_json,
            "catalog_info": VULHUB_CATALOG.get(target.env_id, {}),
        }


# ── Singleton ─────────────────────────────────────────────────────

_vulhub_target_service: Optional[VulhubTargetService] = None


def get_vulhub_target_service() -> VulhubTargetService:
    """Get or create the singleton VulhubTargetService instance."""
    global _vulhub_target_service
    if _vulhub_target_service is None:
        _vulhub_target_service = VulhubTargetService()
    return _vulhub_target_service
