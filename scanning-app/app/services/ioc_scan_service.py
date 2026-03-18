"""IOC scan service for orchestrating LOKI-RS scans on remote filesystems.

This module provides the IocScanService class which orchestrates IOC scans
by creating temporary Kubernetes pods that mount remote filesystems (via SSH
or SMB) and run LOKI-RS to detect malware, YARA rule matches, and hash IOCs.
Results are parsed from JSONL output and uploaded to Faraday.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable, List
from dataclasses import dataclass, field

from app.models.ioc_scan import (
    IocScanState, IocScanStatus, IocSeverity, IocFinding,
    IocScanLogEntry, IocScanRequest, MountType
)
from talos_common.services.process_manager import ProcessManager
from talos_common.services.kubectl_utils import KubernetesHelper
from app.services.faraday_client import FaradayClient
from app.services import result_store
from app.db import engine as db_engine
from talos_common.services.base_service import BaseServiceMixin


logger = logging.getLogger(__name__)

# Timeouts (seconds)
LOKI_SCAN_TIMEOUT = 7200      # 2 hours max for IOC scan
MOUNT_TIMEOUT = 60             # 1 min for filesystem mount
POD_CREATE_TIMEOUT = 30        # 30s for pod creation
FARADAY_UPLOAD_TIMEOUT = 120   # 2 min for Faraday upload

# LOKI-RS container image (hosted in Harbor private registry)
LOKI_IMAGE = "harbor.knowledgeondemand.net/cleanroom/loki-rs-scanner:v2.10.0"

# Namespace for scanner pods
LOKI_NAMESPACE = "loki-scanner"


def _score_to_severity(score: int) -> IocSeverity:
    """Map LOKI-RS numeric score to severity enum."""
    if score >= 80:
        return IocSeverity.ALERT
    elif score >= 60:
        return IocSeverity.WARNING
    return IocSeverity.NOTICE


def _severity_to_faraday(severity: IocSeverity) -> str:
    """Map IOC severity to Faraday severity string."""
    return {
        IocSeverity.ALERT: "critical",
        IocSeverity.WARNING: "high",
        IocSeverity.NOTICE: "medium",
    }.get(severity, "medium")


def _parse_jsonl_line(line: str) -> Optional[IocFinding]:
    """Parse a single JSONL line from LOKI-RS output into an IocFinding.

    LOKI-RS JSONL output contains various record types. We extract
    findings (matches) and ignore status/progress messages.
    """
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    # LOKI-RS outputs different record types; findings have a level field
    level = data.get("level", "").lower()
    if level not in ("alert", "warning", "notice"):
        return None

    score = data.get("score", 0)
    if isinstance(score, str):
        try:
            score = int(score)
        except ValueError:
            score = 0

    file_path = data.get("file", data.get("path", ""))
    rule_name = data.get("rule", data.get("reason", ""))
    description = data.get("message", data.get("description", ""))
    matched_strings = data.get("matched_strings", data.get("matches", []))
    if isinstance(matched_strings, str):
        matched_strings = [matched_strings]

    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return IocFinding(
        severity=_score_to_severity(score),
        score=score,
        file_path=file_path,
        rule_name=rule_name if rule_name else None,
        description=description,
        matched_strings=matched_strings if matched_strings else None,
        hash_md5=data.get("md5"),
        hash_sha256=data.get("sha256"),
        tags=tags,
    )


@dataclass
class IocScanService(BaseServiceMixin):
    """Service for orchestrating LOKI-RS IOC scans.

    Uses BaseServiceMixin for shared patterns (k8s helper, poll_until).
    Uses KubernetesHelper for kubectl operations.
    Uses FaradayClient for Faraday credential and upload operations.
    """

    process_manager: ProcessManager = field(default_factory=ProcessManager)
    current_scan: Optional[IocScanState] = None
    logs: List[IocScanLogEntry] = field(default_factory=list)
    scan_history: List[dict] = field(default_factory=list)
    log_callback: Optional[Callable[[IocScanLogEntry], Awaitable[None]]] = None
    status_callback: Optional[Callable[[IocScanState], Awaitable[None]]] = None

    def __post_init__(self):
        self._k8s_helper = KubernetesHelper(self.process_manager)
        self.faraday_client = FaradayClient(self.process_manager)

    async def log(self, level: str, message: str):
        """Log a message and notify via callback."""
        entry = IocScanLogEntry(
            timestamp=datetime.utcnow(),
            level=level,
            message=message
        )
        await self._log_with_callback(entry, self.log_callback)

    async def _broadcast_state(self):
        """Broadcast current scan state to connected clients."""
        if self.status_callback and self.current_scan:
            try:
                await self.status_callback(self.current_scan)
            except Exception as exc:
                logger.debug("Status broadcast callback failed: %s", exc)

    def is_running(self) -> bool:
        """Check if a scan is currently running."""
        return (self.current_scan is not None and
                self.current_scan.status not in (
                    IocScanStatus.IDLE, IocScanStatus.COMPLETED,
                    IocScanStatus.FAILED, IocScanStatus.ABORTED
                ))

    def get_status(self) -> Optional[IocScanState]:
        """Get current scan state."""
        return self.current_scan

    async def start_scan(
        self,
        request: IocScanRequest,
        log_callback: Optional[Callable] = None,
        status_callback: Optional[Callable] = None
    ) -> IocScanState:
        """Start a new IOC scan."""
        if self.is_running():
            raise ValueError("An IOC scan is already in progress")

        self.log_callback = log_callback
        self.status_callback = status_callback
        self.logs.clear()

        scan = IocScanState(
            id=str(uuid.uuid4())[:8],
            target=request.target,
            mount_type=request.mount_type,
            scan_path=request.scan_path,
            status=IocScanStatus.IDLE,
            started_at=datetime.utcnow(),
        )
        self.current_scan = scan

        # Run the scan in background with error handling
        task = asyncio.create_task(self._run_scan(request))
        task.add_done_callback(self._handle_task_exception)
        return scan

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle unhandled exceptions from background IOC scan tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Background IOC scan task failed with unhandled exception: %s", exc, exc_info=exc)
            if self.current_scan and self.current_scan.status not in (
                IocScanStatus.COMPLETED, IocScanStatus.FAILED, IocScanStatus.ABORTED
            ):
                self.current_scan.status = IocScanStatus.FAILED
                self.current_scan.completed_at = datetime.utcnow()

    async def abort_scan(self) -> bool:
        """Abort the current scan and clean up the pod."""
        if not self.current_scan or not self.is_running():
            return False

        scan = self.current_scan
        scan.status = IocScanStatus.ABORTED
        scan.completed_at = datetime.utcnow()

        # Kill the running pod
        pod_name = f"loki-scan-{scan.id}"
        await self.k8s.delete_pod(LOKI_NAMESPACE, pod_name, force=True, timeout=15)

        await self.process_manager.cancel()
        await self.log("warn", "IOC scan aborted by user")
        await self._broadcast_state()

        # Persist abort to database
        try:
            if db_engine._session_factory is not None:
                async with db_engine._session_factory() as session:
                    await result_store.persist_scan_complete(
                        session,
                        scan_id=scan.id,
                        status="aborted",
                    )
        except Exception as exc:
            logger.warning("DB persistence failed: %s", exc)

        self._save_to_history()
        return True

    async def _run_scan(self, request: IocScanRequest):
        """Execute the full IOC scan workflow."""
        scan = self.current_scan
        try:
            await self.log("info", f"Starting IOC scan against {request.target}")
            await self.log("info", f"Mount: {request.mount_type.value} | Path: {request.scan_path}")

            # Persist scan start to PostgreSQL
            try:
                if db_engine._session_factory is not None:
                    async with db_engine._session_factory() as session:
                        await result_store.persist_scan_start(
                            session,
                            scan_id=scan.id,
                            scan_type="ioc",
                            target=request.target,
                            mount_type=request.mount_type.value,
                            scan_path=request.scan_path,
                        )
            except Exception as exc:
                logger.warning("DB persist scan start failed: %s", exc)

            # Verify kubectl connectivity
            if not await self.k8s.check_connectivity():
                await self.log("error", "Cannot connect to Kubernetes cluster")
                scan.status = IocScanStatus.FAILED
                scan.error_message = "Kubernetes cluster unreachable"
                scan.completed_at = datetime.utcnow()
                await self._broadcast_state()
                try:
                    if db_engine._session_factory is not None:
                        async with db_engine._session_factory() as session:
                            await result_store.persist_scan_complete(
                                session, scan_id=scan.id,
                                status="failed", error_message=scan.error_message,
                            )
                except Exception as exc:
                    logger.warning("DB persistence failed: %s", exc)
                self._save_to_history()
                return

            # Ensure namespace exists with privileged PodSecurity (required for FUSE mounts)
            await self.k8s.ensure_namespace(LOKI_NAMESPACE, privileged=True)

            # Run the LOKI-RS scan pod
            scan.status = IocScanStatus.MOUNTING
            await self._broadcast_state()
            await self.log("info", "Creating LOKI-RS scanner pod...")

            jsonl_output = await self._run_loki_pod(request)

            if jsonl_output is None:
                if scan.status not in (IocScanStatus.ABORTED, IocScanStatus.FAILED):
                    scan.status = IocScanStatus.FAILED
                    scan.error_message = "LOKI-RS scan produced no output"
                    scan.completed_at = datetime.utcnow()
                    await self._broadcast_state()
                # Persist failure/abort to PostgreSQL
                try:
                    if db_engine._session_factory is not None:
                        async with db_engine._session_factory() as session:
                            await result_store.persist_scan_complete(
                                session, scan_id=scan.id,
                                status=scan.status.value,
                                error_message=scan.error_message,
                            )
                except Exception as exc:
                    logger.warning("DB persistence failed: %s", exc)
                self._save_to_history()
                return

            # Parse JSONL findings
            scan.status = IocScanStatus.PARSING
            await self._broadcast_state()
            await self.log("info", "Parsing LOKI-RS results...")

            findings = self._parse_findings(jsonl_output)
            scan.findings = findings
            scan.alerts_count = sum(1 for f in findings if f.severity == IocSeverity.ALERT)
            scan.warnings_count = sum(1 for f in findings if f.severity == IocSeverity.WARNING)
            scan.notices_count = sum(1 for f in findings if f.severity == IocSeverity.NOTICE)

            total = len(findings)
            await self.log("info",
                f"Found {total} IOC(s): {scan.alerts_count} alerts, "
                f"{scan.warnings_count} warnings, {scan.notices_count} notices")
            await self._broadcast_state()

            # Persist IOC findings to PostgreSQL
            try:
                if db_engine._session_factory is not None and findings:
                    async with db_engine._session_factory() as session:
                        # Ensure host exists for the target
                        host_id = await result_store.persist_host(
                            session, scan_id=scan.id, ip=request.target,
                        )
                        for finding in findings:
                            await result_store.persist_ioc_finding(
                                session,
                                scan_id=scan.id,
                                host_id=host_id,
                                severity=finding.severity.value,
                                score=finding.score,
                                file_path=finding.file_path,
                                rule_name=finding.rule_name,
                                description=finding.description,
                                matched_strings=finding.matched_strings,
                                hash_md5=finding.hash_md5,
                                hash_sha256=finding.hash_sha256,
                                tags=finding.tags,
                            )
                    await self.log("info", f"Persisted {total} IOC finding(s) to database")
            except Exception as exc:
                logger.warning("DB persist IOC findings failed: %s", exc)

            # Upload to Faraday
            if findings:
                scan.status = IocScanStatus.UPLOADING
                await self._broadcast_state()

                faraday_creds = await self.faraday_client.get_credentials(
                    log_callback=lambda lvl, msg: self.log(lvl, msg)
                )
                if faraday_creds:
                    await self.faraday_client.ensure_admin(faraday_creds)
                    uploaded = await self._upload_to_faraday(
                        findings, request.target, faraday_creds, scan.id
                    )
                    scan.uploaded_to_faraday = uploaded
                    if uploaded:
                        await self.log("info",
                            "Results uploaded to Faraday workspace 'pentest': "
                            "https://faraday.knowledgeondemand.net")

                    # Persist Faraday sync status
                    try:
                        if db_engine._session_factory is not None:
                            async with db_engine._session_factory() as session:
                                await result_store.persist_faraday_sync(
                                    session,
                                    scan_id=scan.id,
                                    success=uploaded,
                                    scan_type="ioc",
                                    detail=f"IOC upload {'succeeded' if uploaded else 'failed'}",
                                )
                    except Exception as exc:
                        logger.warning("DB persistence failed: %s", exc)
                else:
                    await self.log("warn", "Faraday credentials unavailable, skipping upload")

            # Done
            scan.status = IocScanStatus.COMPLETED
            scan.completed_at = datetime.utcnow()
            await self.log("info", "")
            await self.log("info", "=== IOC Scan Complete ===")
            if scan.alerts_count > 0:
                await self.log("error", f"INDICATORS DETECTED: {scan.alerts_count} alert(s)")
            elif scan.warnings_count > 0:
                await self.log("warn", f"SUSPICIOUS OBJECTS: {scan.warnings_count} warning(s)")
            else:
                await self.log("info", "System appears clean (no alerts or warnings)")
            await self._broadcast_state()

            # Persist scan completion to PostgreSQL
            try:
                if db_engine._session_factory is not None:
                    async with db_engine._session_factory() as session:
                        await result_store.persist_scan_complete(
                            session,
                            scan_id=scan.id,
                            status="completed",
                        )
            except Exception as exc:
                logger.warning("DB persistence failed: %s", exc)

        except Exception as e:
            await self.log("error", f"IOC scan failed: {e}")
            if scan:
                scan.status = IocScanStatus.FAILED
                scan.error_message = str(e)
                scan.completed_at = datetime.utcnow()
                await self._broadcast_state()

                # Persist failure to PostgreSQL
                try:
                    if db_engine._session_factory is not None:
                        async with db_engine._session_factory() as session:
                            await result_store.persist_scan_complete(
                                session,
                                scan_id=scan.id,
                                status="failed",
                                error_message=str(e),
                            )
                except Exception as exc:
                    logger.warning("DB persistence failed: %s", exc)
        finally:
            self._save_to_history()

    async def _run_loki_pod(self, request: IocScanRequest) -> Optional[str]:
        """Create and run the LOKI-RS scanner pod, return JSONL output."""
        scan = self.current_scan
        pod_name = f"loki-scan-{scan.id}"

        # Build environment variables for the entrypoint script
        env_vars = {
            "TARGET": request.target,
            "MOUNT_TYPE": request.mount_type.value,
            "SCAN_PATH": request.scan_path,
            "MAX_FILE_SIZE": str(request.max_file_size_mb * 1024 * 1024),
        }

        if not request.scan_archives:
            env_vars["NO_ARCHIVE"] = "1"

        if request.mount_type == MountType.SSH:
            env_vars["SSH_USER"] = request.ssh_username or "root"
            env_vars["SSH_PASSWORD"] = request.ssh_password or ""
            if request.ssh_key:
                env_vars["SSH_KEY"] = request.ssh_key
        elif request.mount_type == MountType.SMB:
            env_vars["SMB_SHARE"] = request.smb_share or "C$"
            env_vars["SMB_USER"] = request.smb_username or ""
            env_vars["SMB_PASSWORD"] = request.smb_password or ""
            env_vars["SMB_DOMAIN"] = request.smb_domain or "WORKGROUP"

        # Build pod override spec (needed for privileged mode + env vars)
        env_list = [{"name": k, "value": v} for k, v in env_vars.items()]
        pod_override = {
            "apiVersion": "v1",
            "spec": {
                "containers": [{
                    "name": pod_name,
                    "image": LOKI_IMAGE,
                    "env": env_list,
                    "securityContext": {
                        "privileged": True  # Required for FUSE/sshfs mounts
                    },
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "512Mi"},
                        "limits": {"cpu": "2", "memory": "2Gi"}
                    }
                }],
                "restartPolicy": "Never",
                "imagePullSecrets": [{"name": "harbor-pull-secret"}]
            }
        }

        override_json = json.dumps(pod_override)

        # Create the pod
        create_result = await self.k8s.create_pod_from_spec(
            namespace=LOKI_NAMESPACE,
            pod_name=pod_name,
            image=LOKI_IMAGE,
            pod_override_json=override_json,
            timeout=POD_CREATE_TIMEOUT
        )

        if not create_result.success:
            await self.log("error", f"Failed to create LOKI-RS pod: {create_result.output}")
            scan.status = IocScanStatus.FAILED
            scan.error_message = f"Pod creation failed: {create_result.output}"
            return None

        await self.log("info", f"Scanner pod '{pod_name}' created")

        # Wait for pod to start running (mount phase)
        scan.status = IocScanStatus.MOUNTING
        await self._broadcast_state()

        # Poll until pod is Running or completed
        started = False
        for _ in range(MOUNT_TIMEOUT // 5):
            if scan.status == IocScanStatus.ABORTED:
                return None

            phase = await self.k8s.get_pod_phase(LOKI_NAMESPACE, pod_name)

            if phase == "Running":
                started = True
                scan.status = IocScanStatus.SCANNING
                await self._broadcast_state()
                await self.log("info", "Filesystem mounted, LOKI-RS scanning...")
                break
            elif phase in ("Succeeded", "Failed"):
                started = True
                break
            elif phase == "Pending":
                # Check for container errors (e.g., ImagePullBackOff)
                reason = await self.k8s.get_pod_waiting_reason(LOKI_NAMESPACE, pod_name)
                if reason in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
                    await self.log("error", f"Pod failed to start: {reason}")
                    scan.status = IocScanStatus.FAILED
                    scan.error_message = f"Container error: {reason}"
                    await self._cleanup_pod(pod_name)
                    return None

            await asyncio.sleep(5)

        if not started:
            await self.log("error", f"Pod did not start within {MOUNT_TIMEOUT}s")
            scan.status = IocScanStatus.FAILED
            scan.error_message = "Mount timeout"
            await self._cleanup_pod(pod_name)
            return None

        # Poll until pod completes
        scan.status = IocScanStatus.SCANNING
        await self._broadcast_state()

        poll_interval = 5
        max_polls = LOKI_SCAN_TIMEOUT // poll_interval
        pod_done = False

        for attempt in range(max_polls):
            if scan.status == IocScanStatus.ABORTED:
                return None

            phase = await self.k8s.get_pod_phase(LOKI_NAMESPACE, pod_name)

            if phase in ("Succeeded", "Failed"):
                pod_done = True
                await self.log("info", f"Scanner pod finished (phase: {phase})")
                if phase == "Failed":
                    await self.log("warn", "Pod exited with failure — checking logs for partial results")
                break
            elif phase is None or phase == "":
                pod_done = True
                break

            # Stream any new log lines periodically for user feedback
            if attempt > 0 and attempt % 6 == 0:  # Every 30s
                await self.log("info", f"Scan in progress... ({attempt * poll_interval}s elapsed)")

            await asyncio.sleep(poll_interval)

        if not pod_done:
            await self.log("error", f"LOKI-RS scan timed out after {LOKI_SCAN_TIMEOUT}s")
            await self._cleanup_pod(pod_name)
            scan.status = IocScanStatus.FAILED
            scan.error_message = "Scan timeout"
            return None

        # Read pod logs (contains JSONL output)
        logs_result = await self.k8s.get_pod_logs(LOKI_NAMESPACE, pod_name, timeout=60)

        # Clean up pod
        await self._cleanup_pod(pod_name)

        output = (logs_result.output or "").strip()
        if not output:
            await self.log("warn", "LOKI-RS pod produced no output")
            return None

        return output

    async def _cleanup_pod(self, pod_name: str):
        """Delete a scanner pod."""
        await self.k8s.delete_pod(LOKI_NAMESPACE, pod_name, force=True, timeout=15)

    def _parse_findings(self, jsonl_output: str) -> List[IocFinding]:
        """Parse JSONL output from LOKI-RS into findings."""
        findings = []
        for line in jsonl_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            finding = _parse_jsonl_line(line)
            if finding:
                findings.append(finding)

        # Sort by score descending (most severe first)
        findings.sort(key=lambda f: f.score, reverse=True)
        return findings

    # =========================================================================
    # FARADAY INTEGRATION
    # =========================================================================

    async def _upload_to_faraday(self, findings: List[IocFinding], target: str,
                                 creds: dict, scan_id: str) -> bool:
        """Upload IOC findings to Faraday via REST API.

        Delegates to FaradayClient.upload_ioc_findings() which runs a
        Python script inside the Faraday container that creates a host
        for the target and vulns for each IOC finding.
        """
        # Build findings data for the upload
        findings_data = []
        for f in findings:
            findings_data.append({
                "severity": _severity_to_faraday(f.severity),
                "score": f.score,
                "file_path": f.file_path,
                "rule_name": f.rule_name or "Unknown IOC",
                "description": f.description,
                "matched_strings": f.matched_strings or [],
                "hash_md5": f.hash_md5 or "",
                "hash_sha256": f.hash_sha256 or "",
                "tags": f.tags,
            })

        return await self.faraday_client.upload_ioc_findings(
            findings_data=findings_data,
            target=target,
            scan_id=scan_id,
            creds=creds,
            log_callback=lambda lvl, msg: self.log(lvl, msg),
            timeout=FARADAY_UPLOAD_TIMEOUT
        )

    # =========================================================================
    # HISTORY
    # =========================================================================

    def _save_to_history(self):
        """Save completed scan to history."""
        if not self.current_scan:
            return
        scan = self.current_scan
        self.scan_history.append({
            "id": scan.id,
            "target": scan.target,
            "mount_type": scan.mount_type.value,
            "scan_path": scan.scan_path,
            "status": scan.status.value,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "alerts": scan.alerts_count,
            "warnings": scan.warnings_count,
            "notices": scan.notices_count,
            "total_findings": len(scan.findings),
            "uploaded_to_faraday": scan.uploaded_to_faraday,
        })
        # Keep last 50 entries
        if len(self.scan_history) > 50:
            self.scan_history = self.scan_history[-50:]


# Singleton
_ioc_scan_service: Optional[IocScanService] = None


def get_ioc_scan_service() -> IocScanService:
    """Get or create the singleton IocScanService instance."""
    global _ioc_scan_service
    if _ioc_scan_service is None:
        _ioc_scan_service = IocScanService()
    return _ioc_scan_service
