"""IOC scan service for orchestrating LOKI-RS scans on remote filesystems.

This module provides the IocScanService class which orchestrates IOC scans
by creating temporary Kubernetes pods that mount remote filesystems (via SSH
or SMB) and run LOKI-RS to detect malware, YARA rule matches, and hash IOCs.
Results are parsed from JSONL output and uploaded to Faraday.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable, List
from dataclasses import dataclass, field

from app.models.ioc_scan import (
    IocScanState, IocScanStatus, IocSeverity, IocFinding,
    IocScanLogEntry, IocScanRequest, MountType
)
from app.services.process_manager import ProcessManager


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
class IocScanService:
    """Service for orchestrating LOKI-RS IOC scans."""

    process_manager: ProcessManager = field(default_factory=ProcessManager)
    current_scan: Optional[IocScanState] = None
    logs: List[IocScanLogEntry] = field(default_factory=list)
    scan_history: List[dict] = field(default_factory=list)
    log_callback: Optional[Callable[[IocScanLogEntry], Awaitable[None]]] = None
    status_callback: Optional[Callable[[IocScanState], Awaitable[None]]] = None

    async def log(self, level: str, message: str):
        """Log a message and notify via callback."""
        entry = IocScanLogEntry(
            timestamp=datetime.utcnow(),
            level=level,
            message=message
        )
        self.logs.append(entry)
        if self.log_callback:
            try:
                await self.log_callback(entry)
            except Exception:
                pass

    async def _broadcast_state(self):
        """Broadcast current scan state to connected clients."""
        if self.status_callback and self.current_scan:
            try:
                await self.status_callback(self.current_scan)
            except Exception:
                pass

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

        # Run the scan in background
        asyncio.create_task(self._run_scan(request))
        return scan

    async def abort_scan(self) -> bool:
        """Abort the current scan and clean up the pod."""
        if not self.current_scan or not self.is_running():
            return False

        scan = self.current_scan
        scan.status = IocScanStatus.ABORTED
        scan.completed_at = datetime.utcnow()

        # Kill the running pod
        pod_name = f"loki-scan-{scan.id}"
        await self.process_manager.run_command_simple(
            ["kubectl", "delete", "pod", pod_name,
             f"--namespace={LOKI_NAMESPACE}",
             "--ignore-not-found", "--grace-period=0", "--force"],
            timeout=15
        )

        await self.process_manager.cancel()
        await self.log("warn", "IOC scan aborted by user")
        await self._broadcast_state()
        self._save_to_history()
        return True

    async def _run_scan(self, request: IocScanRequest):
        """Execute the full IOC scan workflow."""
        scan = self.current_scan
        try:
            await self.log("info", f"Starting IOC scan against {request.target}")
            await self.log("info", f"Mount: {request.mount_type.value} | Path: {request.scan_path}")

            # Verify kubectl connectivity
            check = await self.process_manager.run_command_simple(
                ["kubectl", "cluster-info", "--request-timeout=5s"],
                timeout=10
            )
            if not check.success:
                await self.log("error", "Cannot connect to Kubernetes cluster")
                scan.status = IocScanStatus.FAILED
                scan.error_message = "Kubernetes cluster unreachable"
                scan.completed_at = datetime.utcnow()
                await self._broadcast_state()
                self._save_to_history()
                return

            # Ensure namespace exists with privileged PodSecurity (required for FUSE mounts)
            await self.process_manager.run_command_simple(
                ["bash", "-c",
                 f"kubectl create namespace {LOKI_NAMESPACE} --dry-run=client -o yaml | kubectl apply -f - && "
                 f"kubectl label namespace {LOKI_NAMESPACE} pod-security.kubernetes.io/enforce=privileged --overwrite"],
                timeout=15
            )

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

            # Upload to Faraday
            if findings:
                scan.status = IocScanStatus.UPLOADING
                await self._broadcast_state()

                faraday_creds = await self._get_faraday_credentials()
                if faraday_creds:
                    await self._ensure_faraday_admin(faraday_creds)
                    uploaded = await self._upload_to_faraday(
                        findings, request.target, faraday_creds, scan.id
                    )
                    scan.uploaded_to_faraday = uploaded
                    if uploaded:
                        await self.log("info",
                            "Results uploaded to Faraday workspace 'pentest': "
                            "https://faraday.knowledgeondemand.net")
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

        except Exception as e:
            await self.log("error", f"IOC scan failed: {e}")
            if scan:
                scan.status = IocScanStatus.FAILED
                scan.error_message = str(e)
                scan.completed_at = datetime.utcnow()
                await self._broadcast_state()
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
        create_result = await self.process_manager.run_command_simple(
            ["kubectl", "run", pod_name,
             f"--image={LOKI_IMAGE}",
             "--restart=Never",
             f"--namespace={LOKI_NAMESPACE}",
             f"--overrides={override_json}"],
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

            phase_result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "pod", pod_name, f"--namespace={LOKI_NAMESPACE}",
                 "-o", "jsonpath={.status.phase}"],
                timeout=10
            )
            phase = (phase_result.output or "").strip()

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
                status_result = await self.process_manager.run_command_simple(
                    ["kubectl", "get", "pod", pod_name, f"--namespace={LOKI_NAMESPACE}",
                     "-o", "jsonpath={.status.containerStatuses[0].state.waiting.reason}"],
                    timeout=10
                )
                reason = (status_result.output or "").strip()
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

            phase_result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "pod", pod_name, f"--namespace={LOKI_NAMESPACE}",
                 "-o", "jsonpath={.status.phase}"],
                timeout=10
            )
            phase = (phase_result.output or "").strip()

            if phase in ("Succeeded", "Failed"):
                pod_done = True
                await self.log("info", f"Scanner pod finished (phase: {phase})")
                if phase == "Failed":
                    await self.log("warn", "Pod exited with failure — checking logs for partial results")
                break
            elif phase == "":
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
        logs_result = await self.process_manager.run_command_simple(
            ["kubectl", "logs", pod_name, f"--namespace={LOKI_NAMESPACE}"],
            timeout=60
        )

        # Clean up pod
        await self._cleanup_pod(pod_name)

        output = (logs_result.output or "").strip()
        if not output:
            await self.log("warn", "LOKI-RS pod produced no output")
            return None

        return output

    async def _cleanup_pod(self, pod_name: str):
        """Delete a scanner pod."""
        await self.process_manager.run_command_simple(
            ["kubectl", "delete", "pod", pod_name,
             f"--namespace={LOKI_NAMESPACE}",
             "--ignore-not-found", "--grace-period=0", "--force"],
            timeout=15
        )

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

    async def _get_faraday_credentials(self) -> Optional[dict]:
        """Get Faraday credentials from k8s secret."""
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "secret", "faraday-credentials", "-n", "faraday",
             "-o", "jsonpath={.data.admin-password}"],
            timeout=10
        )

        if not result.success or not result.output.strip():
            await self.log("warn", "Could not retrieve Faraday credentials")
            return None

        password_b64 = result.output.strip()
        decode_result = await self.process_manager.run_command_simple(
            ["bash", "-c", f"echo '{password_b64}' | base64 -d"],
            timeout=5
        )

        if decode_result.success and decode_result.output.strip():
            return {
                "username": "admin",
                "password": decode_result.output.strip()
            }
        return None

    async def _ensure_faraday_admin(self, creds: dict) -> bool:
        """Ensure the Faraday admin user exists."""
        pod_result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pods", "-n", "faraday", "-l", "app.kubernetes.io/name=faraday",
             "-o", "jsonpath={.items[0].metadata.name}"],
            timeout=10
        )
        if not pod_result.success or not pod_result.output.strip():
            return False

        pod_name = pod_result.output.strip()
        result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "faraday", f"pod/{pod_name}", "-c", "faraday",
             "--", "faraday-manage", "create-superuser",
             "--username", creds["username"],
             "--email", "admin@knowledgeondemand.net",
             "--password", creds["password"]],
            timeout=30
        )
        output = (result.output or "").lower()
        return result.success or "already" in output or "created" in output

    async def _upload_to_faraday(self, findings: List[IocFinding], target: str,
                                 creds: dict, scan_id: str) -> bool:
        """Upload IOC findings to Faraday via REST API.

        Runs a Python script inside the Faraday container that creates
        a host for the target and vulns for each IOC finding.
        """
        await self.log("info", "Uploading IOC findings to Faraday workspace 'pentest'...")

        # Get Faraday pod
        pod_result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "pods", "-n", "faraday", "-l", "app.kubernetes.io/name=faraday",
             "-o", "jsonpath={.items[0].metadata.name}"],
            timeout=10
        )
        if not pod_result.success or not pod_result.output.strip():
            await self.log("warn", "Could not find Faraday pod")
            return False

        pod_name = pod_result.output.strip()

        # Build findings data for the upload script
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

        findings_json = json.dumps(findings_data)

        upload_script = (
            "import urllib.request, json, http.cookiejar, os, sys\n"
            "BASE = 'http://127.0.0.1:5985'\n"
            "WS = 'pentest'\n"
            f"TARGET_IP = '{target}'\n"
            f"SCAN_ID = '{scan_id}'\n"
            "TOOL_TAGS = ['tool:loki-rs', f'scan:{SCAN_ID}']\n"
            "cj = http.cookiejar.CookieJar()\n"
            "opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))\n"
            "csrf = ''\n"
            "\n"
            "def api_post(path, body):\n"
            "    data = json.dumps(body).encode()\n"
            "    req = urllib.request.Request(BASE + path, method='POST',\n"
            "        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, data=data)\n"
            "    resp = opener.open(req)\n"
            "    return json.loads(resp.read().decode())\n"
            "\n"
            "def api_get(path):\n"
            "    req = urllib.request.Request(BASE + path, headers={'X-CSRFToken': csrf})\n"
            "    resp = opener.open(req)\n"
            "    return json.loads(resp.read().decode())\n"
            "\n"
            "# Login\n"
            "try:\n"
            "    data = json.dumps({'email': os.environ['F_USER'], 'password': os.environ['F_PASS']}).encode()\n"
            "    req = urllib.request.Request(BASE + '/_api/login', method='POST',\n"
            "        headers={'Content-Type': 'application/json'}, data=data)\n"
            "    resp = opener.open(req)\n"
            "    login = json.loads(resp.read().decode())\n"
            "    csrf = login['response']['csrf_token']\n"
            "except Exception as e:\n"
            "    print(f'UPLOAD:LOGIN_FAILED:{e}')\n"
            "    sys.exit(0)\n"
            "\n"
            "# Ensure workspace\n"
            "try:\n"
            "    api_get(f'/_api/v3/ws/{WS}')\n"
            "except urllib.error.HTTPError as e:\n"
            "    if e.code == 404:\n"
            "        try:\n"
            "            api_post('/_api/v3/ws', {'name': WS, 'description': 'CleanRoom automated security scans'})\n"
            "        except Exception as we:\n"
            "            print(f'UPLOAD:WS_CREATE_FAILED:{we}')\n"
            "            sys.exit(0)\n"
            "\n"
            "# Create host\n"
            "host_id = None\n"
            "try:\n"
            "    host_body = {'ip': TARGET_IP, 'tags': list(TOOL_TAGS)}\n"
            "    host_resp = api_post(f'/_api/v3/ws/{WS}/hosts', host_body)\n"
            "    host_id = host_resp.get('id')\n"
            "except urllib.error.HTTPError as e:\n"
            "    if e.code == 409:\n"
            "        try:\n"
            "            existing = json.loads(e.read().decode())\n"
            "            host_id = existing.get('object', {}).get('id')\n"
            "        except: pass\n"
            "    if not host_id:\n"
            "        print(f'UPLOAD:HOST_ERROR:{e}')\n"
            "        sys.exit(0)\n"
            "\n"
            "if not host_id:\n"
            "    print('UPLOAD:FAILED:Could not create host')\n"
            "    sys.exit(0)\n"
            "\n"
            "# Read findings from env\n"
            "findings = json.loads(os.environ.get('FINDINGS_JSON', '[]'))\n"
            "\n"
            "created = 0\n"
            "errors = 0\n"
            "for f in findings:\n"
            "    tags = list(TOOL_TAGS) + [f'severity:{f[\"severity\"]}'] + f.get('tags', [])\n"
            "    if f.get('rule_name'):\n"
            "        tags.append(f'rule:{f[\"rule_name\"]}')\n"
            "    desc_parts = [f['description']]\n"
            "    if f.get('file_path'):\n"
            "        desc_parts.append(f'File: {f[\"file_path\"]}')\n"
            "    if f.get('hash_md5'):\n"
            "        desc_parts.append(f'MD5: {f[\"hash_md5\"]}')\n"
            "    if f.get('hash_sha256'):\n"
            "        desc_parts.append(f'SHA256: {f[\"hash_sha256\"]}')\n"
            "    data_parts = []\n"
            "    if f.get('matched_strings'):\n"
            "        data_parts.append('Matched strings: ' + ', '.join(f['matched_strings']))\n"
            "    data_parts.append(f'LOKI-RS Score: {f[\"score\"]}')\n"
            "    vuln_body = {\n"
            "        'name': f.get('rule_name', 'IOC Match'),\n"
            "        'desc': '\\n'.join(desc_parts),\n"
            "        'severity': f['severity'],\n"
            "        'data': '\\n'.join(data_parts),\n"
            "        'tags': tags,\n"
            "        'parent': host_id,\n"
            "        'parent_type': 'Host',\n"
            "        'type': 'Vulnerability',\n"
            "        'external_id': f.get('hash_sha256', ''),\n"
            "    }\n"
            "    try:\n"
            "        api_post(f'/_api/v3/ws/{WS}/vulns', vuln_body)\n"
            "        created += 1\n"
            "    except:\n"
            "        errors += 1\n"
            "\n"
            "if created > 0:\n"
            "    print(f'UPLOAD:OK:{created} vulns created, {errors} errors')\n"
            "else:\n"
            "    print(f'UPLOAD:FAILED:No vulns created ({errors} errors)')\n"
        )

        result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "faraday", f"pod/{pod_name}", "-c", "faraday",
             "--", "env",
             f"F_USER={creds['username']}",
             f"F_PASS={creds['password']}",
             f"FINDINGS_JSON={findings_json}",
             "python3", "-c", upload_script],
            timeout=FARADAY_UPLOAD_TIMEOUT
        )

        output = (result.output or "").strip()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("UPLOAD:OK"):
                detail = line.split(":", 2)[-1]
                await self.log("info", f"Uploaded to Faraday: {detail}")
                return True
            elif line.startswith("UPLOAD:FAILED"):
                detail = line.split(":", 2)[-1]
                await self.log("warn", f"Faraday upload issue: {detail}")
            elif line.startswith("UPLOAD:LOGIN_FAILED"):
                detail = line.split(":", 2)[-1]
                await self.log("error", f"Faraday login failed: {detail}")
            elif line.startswith("UPLOAD:"):
                await self.log("info", f"Faraday: {line}")

        return False

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
