"""Scan service for orchestrating security scans across multiple tools.

This module provides the ScanService class which orchestrates vulnerability
scans using Nmap, OpenVAS, and Metasploit, then uploads results to Faraday
for consolidated vulnerability management.
"""

import asyncio
import re
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable, List
from dataclasses import dataclass, field

from app.models.scan import (
    ScanState, ScanStatus, ScanTool, ScanProfile,
    ScanToolState, ScanLogEntry, ScanRequest
)
from app.services.process_manager import ProcessManager


# Scan timeout defaults (seconds)
NMAP_TIMEOUT_QUICK = 300       # 5 min for ping sweep
NMAP_TIMEOUT_STANDARD = 900    # 15 min for service detection
NMAP_TIMEOUT_THOROUGH = 3600   # 60 min for full port scan
OPENVAS_TIMEOUT = 7200         # 2 hours for OpenVAS
METASPLOIT_TIMEOUT_QUICK = 900       # 15 min for quick scan
METASPLOIT_TIMEOUT_STANDARD = 5400   # 90 min for standard scan (11 vuln modules)
METASPLOIT_TIMEOUT_THOROUGH = 10800  # 3 hours for thorough scan (39 vuln modules)
FARADAY_UPLOAD_TIMEOUT = 120   # 2 min for Faraday upload (individual REST calls)

# Nmap flags per profile
NMAP_PROFILES = {
    ScanProfile.QUICK: ["-T4", "--top-ports", "100"],
    ScanProfile.STANDARD: ["-sV", "-sC"],
    ScanProfile.THOROUGH: ["-sV", "-sC", "-p-", "-A"],
}

# OpenVAS scan config UUIDs (standard across all Greenbone installations)
OPENVAS_SCAN_CONFIGS = {
    ScanProfile.QUICK: "d21f6c81-2b88-4ac1-b7b4-a2a9f2ad4663",     # Host Discovery
    ScanProfile.STANDARD: "daba56c8-73ec-11df-a475-002264764cea",   # Full and Fast
    ScanProfile.THOROUGH: "698f691e-7489-11df-9d8c-002264764cea",   # Full and Deep
}

# Greenbone XML report format UUID
OPENVAS_XML_FORMAT = "a994b278-1f62-11e1-96ac-406186ea4fc5"


@dataclass
class ScanService:
    """Service for orchestrating security scans."""

    process_manager: ProcessManager = field(default_factory=ProcessManager)
    current_scan: Optional[ScanState] = None
    logs: List[ScanLogEntry] = field(default_factory=list)
    scan_history: List[dict] = field(default_factory=list)
    log_callback: Optional[Callable[[ScanLogEntry], Awaitable[None]]] = None
    tool_callback: Optional[Callable[[ScanToolState], Awaitable[None]]] = None

    async def log(self, tool: Optional[str], level: str, message: str):
        """Log a message and notify via callback."""
        entry = ScanLogEntry(
            timestamp=datetime.utcnow(),
            tool=tool,
            level=level,
            message=message
        )
        self.logs.append(entry)
        if self.log_callback:
            try:
                await self.log_callback(entry)
            except Exception:
                pass  # Don't let broadcast failures crash the scan

    async def _update_tool_state(self, tool: ScanTool, **kwargs):
        """Update a tool's state and notify via callback."""
        if not self.current_scan:
            return
        for ts in self.current_scan.tools:
            if ts.tool == tool:
                for key, value in kwargs.items():
                    setattr(ts, key, value)
                if self.tool_callback:
                    try:
                        await self.tool_callback(ts)
                    except Exception:
                        pass  # Don't let broadcast failures crash the scan
                break

    def get_status(self) -> Optional[ScanState]:
        """Get current scan status."""
        return self.current_scan

    def is_running(self) -> bool:
        """Check if a scan is currently running."""
        return (self.current_scan is not None and
                self.current_scan.status == ScanStatus.RUNNING)

    async def start_scan(
        self,
        request: ScanRequest,
        log_callback: Optional[Callable[[ScanLogEntry], Awaitable[None]]] = None,
        tool_callback: Optional[Callable[[ScanToolState], Awaitable[None]]] = None
    ) -> ScanState:
        """Start a new scan."""
        if self.is_running():
            raise RuntimeError("Scan already in progress")

        if log_callback is not None:
            self.log_callback = log_callback
        if tool_callback is not None:
            self.tool_callback = tool_callback
        self.logs = []

        # Validate target format
        target = request.target.strip()
        if not self._validate_target(target):
            raise ValueError(f"Invalid target: {target}")

        # Initialize scan state
        self.current_scan = ScanState(
            id=str(uuid.uuid4())[:8],
            target=target,
            profile=request.profile,
            status=ScanStatus.RUNNING,
            started_at=datetime.utcnow(),
            tools=[
                ScanToolState(tool=tool)
                for tool in request.tools
            ]
        )

        # Run scan in background
        asyncio.create_task(self._run_scan())

        return self.current_scan

    async def abort_scan(self) -> bool:
        """Abort the current scan."""
        if not self.is_running():
            return False

        await self.process_manager.cancel()
        self.current_scan.status = ScanStatus.ABORTED
        self.current_scan.completed_at = datetime.utcnow()

        # Mark any running tools as aborted
        for ts in self.current_scan.tools:
            if ts.status == ScanStatus.RUNNING:
                ts.status = ScanStatus.ABORTED
                ts.completed_at = datetime.utcnow()
                if self.tool_callback:
                    await self.tool_callback(ts)

        await self.log(None, "warn", "Scan aborted by user")
        self._save_to_history()
        return True

    def _validate_target(self, target: str) -> bool:
        """Validate target is an IP address, CIDR, or hostname."""
        # Allow IP addresses, CIDR notation, hostnames
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$'
        hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$'
        # Allow comma-separated or space-separated targets
        targets = re.split(r'[,\s]+', target)
        for t in targets:
            t = t.strip()
            if not t:
                continue
            if not (re.match(ip_pattern, t) or re.match(hostname_pattern, t)):
                return False
        return len(targets) > 0

    async def _run_scan(self):
        """Execute the scan workflow."""
        try:
            scan = self.current_scan
            target = scan.target
            profile = scan.profile

            await self.log(None, "info", f"Starting security scan against {target}")
            await self.log(None, "info", f"Profile: {profile.value} | Tools: {', '.join(t.tool.value for t in scan.tools)}")

            # Check kubectl is available
            check = await self.process_manager.run_command_simple(
                ["kubectl", "cluster-info", "--request-timeout=5s"],
                timeout=10
            )
            if not check.success:
                await self.log(None, "error", "Cannot connect to Kubernetes cluster. Is the deployment complete?")
                scan.status = ScanStatus.FAILED
                scan.completed_at = datetime.utcnow()
                self._save_to_history()
                return

            # Get Faraday credentials and ensure admin user exists
            faraday_creds = await self._get_faraday_credentials()
            if faraday_creds:
                await self._ensure_faraday_admin(faraday_creds)

            # Run each tool sequentially (to avoid resource contention)
            for tool_state in scan.tools:
                if scan.status != ScanStatus.RUNNING:
                    break

                tool = tool_state.tool
                await self.log(tool.value, "info", f"--- Starting {tool.value.upper()} scan ---")
                await self._update_tool_state(tool, status=ScanStatus.RUNNING, started_at=datetime.utcnow())

                xml_result = None
                try:
                    if tool == ScanTool.NMAP:
                        xml_result = await self._run_nmap_scan(target, profile)
                    elif tool == ScanTool.OPENVAS:
                        xml_result = await self._run_openvas_scan(target, profile)
                    elif tool == ScanTool.METASPLOIT:
                        xml_result = await self._run_metasploit_scan(target, profile)

                    if xml_result and scan.status == ScanStatus.RUNNING:
                        await self._update_tool_state(tool, status=ScanStatus.COMPLETED, completed_at=datetime.utcnow())
                        await self.log(tool.value, "info", f"{tool.value.upper()} scan completed")

                        # Upload to Faraday
                        if faraday_creds:
                            uploaded = await self._upload_to_faraday(xml_result, tool.value, faraday_creds)
                            await self._update_tool_state(tool, uploaded_to_faraday=uploaded)
                        else:
                            await self.log(tool.value, "warn", "Faraday credentials unavailable, skipping upload")
                    elif scan.status == ScanStatus.RUNNING:
                        await self._update_tool_state(
                            tool, status=ScanStatus.FAILED,
                            completed_at=datetime.utcnow(),
                            error_message="No scan output produced"
                        )
                        await self.log(tool.value, "error", f"{tool.value.upper()} scan produced no results")

                except Exception as e:
                    await self._update_tool_state(
                        tool, status=ScanStatus.FAILED,
                        completed_at=datetime.utcnow(),
                        error_message=str(e)
                    )
                    await self.log(tool.value, "error", f"{tool.value.upper()} scan failed: {e}")

            # Final status
            if scan.status == ScanStatus.RUNNING:
                completed_tools = sum(1 for t in scan.tools if t.status == ScanStatus.COMPLETED)
                total_tools = len(scan.tools)
                uploaded_tools = sum(1 for t in scan.tools if t.uploaded_to_faraday)

                scan.status = ScanStatus.COMPLETED
                scan.completed_at = datetime.utcnow()

                await self.log(None, "info", "")
                await self.log(None, "info", "=== Scan Complete ===")
                await self.log(None, "info", f"Tools: {completed_tools}/{total_tools} succeeded")
                await self.log(None, "info", f"Faraday uploads: {uploaded_tools}/{completed_tools}")
                if uploaded_tools > 0:
                    await self.log(None, "info",
                        "Results available in Faraday workspace 'pentest': "
                        "https://faraday.knowledgeondemand.net")

        except Exception as e:
            await self.log(None, "error", f"Scan failed: {e}")
            if self.current_scan:
                self.current_scan.status = ScanStatus.FAILED
                self.current_scan.completed_at = datetime.utcnow()
        finally:
            self._save_to_history()

    # =========================================================================
    # NMAP
    # =========================================================================

    async def _run_nmap_scan(self, target: str, profile: ScanProfile) -> Optional[str]:
        """Run an Nmap scan via a temporary Kubernetes pod."""
        scan_id = self.current_scan.id
        pod_name = f"nmap-scan-{scan_id}"
        flags = NMAP_PROFILES.get(profile, NMAP_PROFILES[ScanProfile.STANDARD])

        timeout = {
            ScanProfile.QUICK: NMAP_TIMEOUT_QUICK,
            ScanProfile.STANDARD: NMAP_TIMEOUT_STANDARD,
            ScanProfile.THOROUGH: NMAP_TIMEOUT_THOROUGH,
        }.get(profile, NMAP_TIMEOUT_STANDARD)

        await self.log("nmap", "info", f"Launching Nmap pod '{pod_name}' with flags: {' '.join(flags)}")

        # Create the nmap pod (don't use --attach/--rm since stdout capture is unreliable)
        # Instead: create pod → wait for completion → read logs → delete pod
        nmap_args_str = " ".join(flags + ["-oX", "-", target])
        create_result = await self.process_manager.run_command_simple(
            ["kubectl", "run", pod_name,
             "--image=instrumentisto/nmap:latest",
             "--restart=Never",
             "--namespace=default",
             "--", "nmap"] + flags + ["-oX", "-", target],
            timeout=30
        )

        if not create_result.success:
            await self.log("nmap", "error", f"Failed to create Nmap pod: {create_result.output}")
            return None

        await self.log("nmap", "info", "Nmap pod created, waiting for scan to complete...")

        # Wait for pod to complete
        wait_result = await self.process_manager.run_command_simple(
            ["kubectl", "wait", "--for=condition=Ready=false",
             f"pod/{pod_name}", "--namespace=default",
             f"--timeout={timeout}s"],
            timeout=timeout + 30
        )

        # Also wait for the pod phase to be Succeeded/Failed
        # (kubectl wait --for=condition doesn't work well for completed pods)
        poll_attempts = timeout // 5
        pod_done = False
        for attempt in range(poll_attempts):
            phase_result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "pod", pod_name, "--namespace=default",
                 "-o", "jsonpath={.status.phase}"],
                timeout=10
            )
            phase = (phase_result.output or "").strip()
            if phase in ("Succeeded", "Failed"):
                pod_done = True
                await self.log("nmap", "info", f"Nmap pod finished (phase: {phase})")
                break
            elif phase == "":
                # Pod may have been deleted already
                pod_done = True
                break
            await asyncio.sleep(5)

        if not pod_done:
            await self.log("nmap", "error", f"Nmap scan timed out after {timeout}s")
            await self.process_manager.run_command_simple(
                ["kubectl", "delete", "pod", pod_name, "--namespace=default",
                 "--ignore-not-found", "--grace-period=0", "--force"],
                timeout=15
            )
            return None

        # Read the pod logs (contains nmap XML output)
        logs_result = await self.process_manager.run_command_simple(
            ["kubectl", "logs", pod_name, "--namespace=default"],
            timeout=30
        )

        # Clean up the pod
        await self.process_manager.run_command_simple(
            ["kubectl", "delete", "pod", pod_name, "--namespace=default",
             "--ignore-not-found", "--grace-period=0", "--force"],
            timeout=15
        )

        output = logs_result.output or ""

        # Extract XML content from output
        xml_start = output.find("<?xml")
        xml_end = output.rfind("</nmaprun>")

        if xml_start >= 0 and xml_end >= 0:
            xml_content = output[xml_start:xml_end + len("</nmaprun>")]
            # Count hosts found
            host_count = xml_content.count("<host ")
            await self.log("nmap", "info", f"Nmap found {host_count} host(s)")

            # Update findings count
            for ts in self.current_scan.tools:
                if ts.tool == ScanTool.NMAP:
                    ts.findings_count = host_count
                    break

            return xml_content
        else:
            # Log raw output for debugging
            output_len = len(output)
            await self.log("nmap", "warn", f"Could not extract XML from Nmap output ({output_len} bytes)")
            for line in output.split("\n")[-30:]:
                line = line.strip()
                if line:
                    await self.log("nmap", "info", f"  {line}")
            return None

    # =========================================================================
    # OPENVAS
    # =========================================================================

    async def _run_openvas_scan(self, target: str, profile: ScanProfile) -> Optional[str]:
        """Run an OpenVAS scan via GMP protocol inside the gvmd container."""
        scan_id = self.current_scan.id
        config_id = OPENVAS_SCAN_CONFIGS.get(profile, OPENVAS_SCAN_CONFIGS[ScanProfile.STANDARD])

        await self.log("openvas", "info", "Connecting to OpenVAS GVM daemon...")

        # Get OpenVAS admin password from k8s secret
        cred_result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "secret", "openvas-credentials", "-n", "openvas",
             "-o", "jsonpath={.data.admin-password}"],
            timeout=10
        )

        if not cred_result.success or not cred_result.output.strip():
            await self.log("openvas", "error", "Could not retrieve OpenVAS credentials from cluster")
            return None

        # Decode base64 password
        password_b64 = cred_result.output.strip()
        decode_result = await self.process_manager.run_command_simple(
            ["bash", "-c", f"echo '{password_b64}' | base64 -d"],
            timeout=5
        )
        openvas_password = decode_result.output.strip() if decode_result.success else ""

        if not openvas_password:
            await self.log("openvas", "error", "Failed to decode OpenVAS password")
            return None

        # Python GMP script that runs inside the gvmd container
        # Uses stdlib only: socket + xml.etree.ElementTree
        gmp_script = self._build_gmp_script(scan_id, target, config_id)

        await self.log("openvas", "info", f"Creating scan target and task for {target}...")

        # Execute the GMP script inside the gvmd container
        result = await self.process_manager.run_command(
            ["kubectl", "exec", "-n", "openvas", "deployment/greenbone", "-c", "gvmd",
             "--", "env", f"GMP_PASSWORD={openvas_password}",
             "python3", "-c", gmp_script],
            on_output=lambda line: self._log_openvas_line(line),
            timeout=OPENVAS_TIMEOUT
        )

        output = result.output or ""

        # Parse status lines from the script
        if "SCAN:FAILED" in output:
            error_line = [l for l in output.split("\n") if "SCAN:FAILED" in l]
            await self.log("openvas", "error", f"OpenVAS scan failed: {error_line}")
            return None

        # Extract XML report from output
        xml_start = output.find("<?xml")
        # The GMP response wraps the report - find the actual report content
        report_start = output.find("<report ")
        report_end = output.rfind("</report>")

        if xml_start >= 0:
            # If we got a full XML document
            xml_end = output.rfind("</report>")
            if xml_end >= 0:
                xml_content = output[xml_start:xml_end + len("</report>")]
                result_count = xml_content.count("<result ")
                await self.log("openvas", "info", f"OpenVAS found {result_count} result(s)")
                for ts in self.current_scan.tools:
                    if ts.tool == ScanTool.OPENVAS:
                        ts.findings_count = result_count
                        break
                return xml_content

        # Try to get the REPORT_XML tagged output from our script
        xml_marker = "REPORT_XML_START"
        xml_end_marker = "REPORT_XML_END"
        if xml_marker in output and xml_end_marker in output:
            start_idx = output.index(xml_marker) + len(xml_marker) + 1
            end_idx = output.index(xml_end_marker)
            xml_content = output[start_idx:end_idx].strip()
            if xml_content:
                result_count = xml_content.count("<result ")
                await self.log("openvas", "info", f"OpenVAS found {result_count} result(s)")
                for ts in self.current_scan.tools:
                    if ts.tool == ScanTool.OPENVAS:
                        ts.findings_count = result_count
                        break
                return xml_content

        await self.log("openvas", "warn", "Could not extract XML report from OpenVAS output")
        return None

    async def _log_openvas_line(self, line: str):
        """Process and log OpenVAS output lines."""
        line = line.strip()
        if not line or line.startswith("<?xml") or line.startswith("<"):
            return  # Don't log XML content
        if line.startswith("STATUS:"):
            await self.log("openvas", "info", line.replace("STATUS:", "").strip())
        elif line.startswith("ERROR:"):
            await self.log("openvas", "error", line.replace("ERROR:", "").strip())
        elif line.startswith("PROGRESS:"):
            await self.log("openvas", "info", line.replace("PROGRESS:", "").strip())

    def _build_gmp_script(self, scan_id: str, target: str, config_id: str) -> str:
        """Build a self-contained Python GMP script for OpenVAS scanning."""
        return f'''
import socket, os, sys, time
import xml.etree.ElementTree as ET

SOCK_PATH = "/run/gvmd/gvmd.sock"
PASSWORD = os.environ.get("GMP_PASSWORD", "")
TARGET = "{target}"
CONFIG_ID = "{config_id}"
SCAN_ID = "{scan_id}"
REPORT_FORMAT = "{OPENVAS_XML_FORMAT}"

def send_gmp(sock, xml_str):
    """Send a GMP command and receive the response."""
    sock.sendall(xml_str.encode("utf-8"))
    response = b""
    while True:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk
            # GMP responses end with a closing tag
            text = response.decode("utf-8", errors="replace")
            for tag in ["authenticate_response", "create_target_response",
                        "create_task_response", "start_task_response",
                        "get_tasks_response", "get_reports_response",
                        "delete_target_response", "delete_task_response"]:
                if f"</{tag}>" in text:
                    return text
        except socket.timeout:
            break
    return response.decode("utf-8", errors="replace")

def get_attr(xml_text, tag, attr):
    """Extract an attribute from the first occurrence of a tag."""
    try:
        root = ET.fromstring(xml_text)
        elem = root if root.tag.endswith("_response") else root
        return elem.attrib.get(attr, "")
    except ET.ParseError:
        return ""

def get_status(xml_text):
    """Get the status code from a GMP response."""
    return get_attr(xml_text, "", "status")

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(SOCK_PATH)
    print("STATUS: Connected to GVM daemon")

    # Authenticate
    auth_xml = f'<authenticate><credentials><username>admin</username><password>{{PASSWORD}}</password></credentials></authenticate>'
    resp = send_gmp(sock, auth_xml)
    if get_status(resp) != "200":
        print(f"SCAN:FAILED:Authentication failed")
        sys.exit(1)
    print("STATUS: Authenticated with GVM")

    # Create target
    target_name = f"scan-{{SCAN_ID}}-target"
    create_target = f'<create_target><name>{{target_name}}</name><hosts>{{TARGET}}</hosts></create_target>'
    resp = send_gmp(sock, create_target)
    status = get_status(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create target failed (status {{status}})")
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        target_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse target ID")
        sys.exit(1)
    print(f"STATUS: Created target {{target_id}}")

    # Create task
    task_name = f"scan-{{SCAN_ID}}-task"
    create_task = f'<create_task><name>{{task_name}}</name><target id="{{target_id}}"/><config id="{{CONFIG_ID}}"/></create_task>'
    resp = send_gmp(sock, create_task)
    status = get_status(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create task failed (status {{status}})")
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        task_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse task ID")
        sys.exit(1)
    print(f"STATUS: Created task {{task_id}}")

    # Start task
    start = f'<start_task task_id="{{task_id}}"/>'
    resp = send_gmp(sock, start)
    status = get_status(resp)
    if status not in ("200", "202"):
        print(f"SCAN:FAILED:Start task failed (status {{status}})")
        sys.exit(1)
    # Extract report ID from start response
    try:
        root = ET.fromstring(resp)
        report_elem = root.find(".//report_id")
        report_id = report_elem.text if report_elem is not None else ""
    except:
        report_id = ""
    print(f"STATUS: Scan started (report {{report_id}})")

    # Poll for completion
    max_polls = 720  # 2 hours at 10s intervals
    for i in range(max_polls):
        time.sleep(10)
        get_task = f'<get_tasks task_id="{{task_id}}"/>'
        resp = send_gmp(sock, get_task)
        try:
            root = ET.fromstring(resp)
            task_elem = root.find(".//task")
            if task_elem is not None:
                task_status = task_elem.findtext("status", "")
                progress_elem = task_elem.find("progress")
                progress = progress_elem.text if progress_elem is not None else "0"
                print(f"PROGRESS: {{task_status}} ({{progress}}%)")
                if task_status == "Done":
                    # Get the report ID from the task
                    if not report_id:
                        report_elem = task_elem.find(".//report")
                        report_id = report_elem.attrib.get("id", "") if report_elem is not None else ""
                    break
                elif task_status in ("Stop Requested", "Stopped", "Error"):
                    print(f"SCAN:FAILED:Task ended with status {{task_status}}")
                    sys.exit(1)
        except ET.ParseError:
            pass
    else:
        print("SCAN:FAILED:Scan timed out after 2 hours")
        sys.exit(1)

    # Get report in XML format
    if report_id:
        print("STATUS: Retrieving scan report...")
        get_report = f'<get_reports report_id="{{report_id}}" format_id="{{REPORT_FORMAT}}" details="1"/>'
        # Need larger timeout for report retrieval
        sock.settimeout(120)
        resp = send_gmp(sock, get_report)
        print("REPORT_XML_START")
        # Extract the report XML from the GMP response
        try:
            root = ET.fromstring(resp)
            report_elem = root.find(".//report")
            if report_elem is not None:
                print(ET.tostring(report_elem, encoding="unicode"))
            else:
                print(resp)
        except:
            print(resp)
        print("REPORT_XML_END")
    else:
        print("SCAN:FAILED:No report ID available")

    # Cleanup: delete task and target
    try:
        send_gmp(sock, f'<delete_task task_id="{{task_id}}" ultimate="1"/>')
        send_gmp(sock, f'<delete_target target_id="{{target_id}}" ultimate="1"/>')
    except:
        pass

    sock.close()
    print("STATUS: OpenVAS scan complete")

except Exception as e:
    print(f"SCAN:FAILED:{{e}}")
    sys.exit(1)
'''

    # =========================================================================
    # METASPLOIT
    # =========================================================================

    def _build_msf_resource_script(self, target: str, profile: ScanProfile,
                                     scan_id: str, xml_path: str) -> str:
        """Build a Metasploit resource script based on scan profile.

        Quick:    db_nmap discovery only (fast port scan, no vuln modules)
        Standard: db_nmap service detection + common vulnerability scanners
        Thorough: db_nmap full scan + comprehensive auxiliary scanner suite
        """
        lines = []

        # Phase 1: Network discovery via db_nmap
        # Use lighter nmap flags here — the standalone Nmap tool already does the
        # comprehensive port scan. Metasploit's db_nmap just populates the MSF
        # database so vulnerability modules know which hosts/ports to target.
        nmap_flags = {
            ScanProfile.QUICK: "-T4 --top-ports 100",
            ScanProfile.STANDARD: "-T4 -sV --top-ports 1000",
            ScanProfile.THOROUGH: "-T4 -sV -sC --top-ports 1000",
        }.get(profile, "-T4 -sV --top-ports 1000")

        lines.append(f"db_nmap {nmap_flags} {target}")

        # Helper to add a module block
        def add_module(mod, extra_opts=None):
            lines.append(f"use {mod}")
            lines.append(f"set RHOSTS {target}")
            lines.append(f"set THREADS 5")
            if extra_opts:
                for k, v in extra_opts.items():
                    lines.append(f"set {k} {v}")
            lines.append(f"run")
            lines.append(f"back")

        # =============================================================
        # STANDARD profile: Critical CVEs + core service scanners
        # =============================================================
        if profile in (ScanProfile.STANDARD, ScanProfile.THOROUGH):

            # --- Critical CVE Checks ---
            add_module("auxiliary/scanner/smb/smb_ms17_010")       # EternalBlue (MS17-010) — critical RCE
            add_module("auxiliary/scanner/smb/smb_ms08_067")       # Conficker (MS08-067) — critical RCE
            add_module("auxiliary/scanner/rdp/cve_2019_0708_bluekeep")  # BlueKeep (CVE-2019-0708)
            add_module("auxiliary/scanner/ssl/openssl_heartbleed") # Heartbleed (CVE-2014-0160)
            add_module("auxiliary/scanner/http/log4shell_scanner") # Log4Shell (CVE-2021-44228)
            add_module("auxiliary/scanner/http/apache_mod_cgi_bash_env")  # Shellshock (CVE-2014-6271)
            add_module("auxiliary/scanner/http/ms15_034_http_sys_memory_dump")  # HTTP.sys (MS15-034)

            # --- Core Service Detection ---
            add_module("auxiliary/scanner/smb/smb_version")        # SMB version fingerprint
            add_module("auxiliary/scanner/ssh/ssh_version")        # SSH version fingerprint
            add_module("auxiliary/scanner/http/http_version")      # HTTP server fingerprint
            add_module("auxiliary/scanner/ftp/anonymous")          # FTP anonymous access

        # =============================================================
        # THOROUGH profile: All Standard + extended scanners
        # =============================================================
        if profile == ScanProfile.THOROUGH:

            # --- Extended SMB ---
            add_module("auxiliary/scanner/smb/smb_enumshares")     # SMB share enumeration
            add_module("auxiliary/scanner/smb/smb_enumusers")      # SMB user enumeration
            add_module("auxiliary/scanner/smb/pipe_auditor")       # SMB named pipe auditing

            # --- Extended RDP ---
            add_module("auxiliary/scanner/rdp/rdp_scanner")        # RDP service detection

            # --- Extended SSH ---
            add_module("auxiliary/scanner/ssh/ssh_enumusers",      # SSH user enumeration
                       {"USER_FILE": "/opt/metasploit-framework/data/wordlists/unix_users.txt"})

            # --- Extended HTTP/Web ---
            add_module("auxiliary/scanner/http/title")             # HTTP page title
            add_module("auxiliary/scanner/http/dir_scanner")       # HTTP directory brute-force
            add_module("auxiliary/scanner/http/robots_txt")        # robots.txt discovery
            add_module("auxiliary/scanner/http/http_put")          # HTTP PUT method test
            add_module("auxiliary/scanner/http/tomcat_mgr_login")  # Tomcat default creds
            add_module("auxiliary/scanner/http/wordpress_scanner") # WordPress detection
            add_module("auxiliary/scanner/http/jenkins_enum")      # Jenkins open dashboard
            add_module("auxiliary/scanner/http/webdav_scanner")    # WebDAV detection

            # --- SSL/TLS Extended ---
            add_module("auxiliary/scanner/ssl/ssl_version")        # SSL/TLS version analysis

            # --- FTP Extended ---
            add_module("auxiliary/scanner/ftp/ftp_version")        # FTP version fingerprint

            # --- Email ---
            add_module("auxiliary/scanner/smtp/smtp_version")      # SMTP version
            add_module("auxiliary/scanner/smtp/smtp_relay")        # Open SMTP relay check
            add_module("auxiliary/scanner/pop3/pop3_version")      # POP3 version

            # --- Database Scanners ---
            add_module("auxiliary/scanner/mysql/mysql_version")    # MySQL version
            add_module("auxiliary/scanner/postgres/postgres_version")  # PostgreSQL version
            add_module("auxiliary/scanner/mssql/mssql_ping")       # MSSQL discovery
            add_module("auxiliary/scanner/mongodb/mongodb_login")  # MongoDB unauth access
            add_module("auxiliary/scanner/redis/redis_server")     # Redis open access

            # --- Network Infrastructure ---
            add_module("auxiliary/scanner/telnet/telnet_version")  # Telnet version
            add_module("auxiliary/scanner/snmp/snmp_enum")         # SNMP enumeration
            add_module("auxiliary/scanner/netbios/nbname")         # NetBIOS name resolution
            add_module("auxiliary/scanner/discovery/udp_sweep")    # UDP service discovery

            # --- Remote Access ---
            add_module("auxiliary/scanner/vnc/vnc_none_auth")      # VNC no-auth check

        # Print discovered vulns summary
        lines.append("vulns")

        # Export results
        lines.append(f"db_export -f xml {xml_path}")
        lines.append("exit")

        return "\n".join(lines) + "\n"

    async def _run_metasploit_scan(self, target: str, profile: ScanProfile) -> Optional[str]:
        """Run a Metasploit scan via resource script with vulnerability modules."""
        scan_id = self.current_scan.id
        xml_path = f"/tmp/msf-scan-{scan_id}.xml"
        rc_path = f"/tmp/scan-{scan_id}.rc"

        # Select timeout based on profile
        msf_timeout = {
            ScanProfile.QUICK: METASPLOIT_TIMEOUT_QUICK,
            ScanProfile.STANDARD: METASPLOIT_TIMEOUT_STANDARD,
            ScanProfile.THOROUGH: METASPLOIT_TIMEOUT_THOROUGH,
        }.get(profile, METASPLOIT_TIMEOUT_STANDARD)

        # Build the resource script
        rc_content = self._build_msf_resource_script(target, profile, scan_id, xml_path)

        module_count = rc_content.count("use auxiliary/")
        if module_count > 0:
            await self.log("metasploit", "info",
                f"Preparing resource script: db_nmap + {module_count} vulnerability scanner module(s)")
        else:
            await self.log("metasploit", "info", "Preparing resource script: db_nmap discovery only")

        # Write resource script into the container via heredoc (handles newlines properly)
        write_rc = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "bash", "-c", f"cat > {rc_path} << 'RCEOF'\n{rc_content}RCEOF"],
            timeout=15
        )

        if not write_rc.success:
            await self.log("metasploit", "error", f"Failed to write resource script: {write_rc.output}")
            return None

        nmap_flags = {
            ScanProfile.QUICK: "-T4 --top-ports 100",
            ScanProfile.STANDARD: "-T4 -sV --top-ports 1000",
            ScanProfile.THOROUGH: "-T4 -sV -sC --top-ports 1000",
        }.get(profile, "-T4 -sV --top-ports 1000")
        await self.log("metasploit", "info", f"Phase 1: db_nmap {nmap_flags} {target}")
        if module_count > 0:
            await self.log("metasploit", "info", f"Phase 2: Running {module_count} auxiliary scanner(s)...")

        # Run msfconsole with the resource script
        result = await self.process_manager.run_command(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "./msfconsole", "-q", "-r", rc_path],
            on_output=lambda line: self._log_msf_line(line),
            timeout=msf_timeout
        )

        if not result.success and "TIMEOUT" in (result.output or ""):
            await self.log("metasploit", "error", "Metasploit scan timed out")
            return None

        # Read the exported XML file
        await self.log("metasploit", "info", "Reading Metasploit export...")
        xml_result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "cat", xml_path],
            timeout=30
        )

        # Cleanup temp files
        await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "bash", "-c", f"rm -f {rc_path} {xml_path}"],
            timeout=10
        )

        if xml_result.success and xml_result.output and "<?xml" in xml_result.output:
            xml_content = xml_result.output.strip()
            host_count = xml_content.count("<host>")
            service_count = xml_content.count("<service>")
            vuln_count = xml_content.count("<vuln>")
            await self.log("metasploit", "info",
                f"Metasploit found {host_count} host(s), {service_count} service(s), {vuln_count} vuln(s)")

            for ts in self.current_scan.tools:
                if ts.tool == ScanTool.METASPLOIT:
                    ts.findings_count = vuln_count if vuln_count > 0 else host_count
                    break

            return xml_content
        else:
            await self.log("metasploit", "warn", "No XML output from Metasploit export")
            if xml_result.output:
                for line in xml_result.output.split("\n")[-10:]:
                    if line.strip():
                        await self.log("metasploit", "info", f"  {line.strip()}")
            return None

    async def _log_msf_line(self, line: str):
        """Process and log Metasploit output lines."""
        line = line.strip()
        if not line:
            return
        # Filter out noisy MSF banner/prompt lines
        if line.startswith("=") or line.startswith("[*] ==="):
            return
        if "metasploit" in line.lower() and "http" not in line and "ms17" not in line.lower():
            return
        # Vulnerability findings (green [+] = positive hit)
        if line.startswith("[+]"):
            await self.log("metasploit", "warn", line)  # yellow for vuln findings
        elif line.startswith("[-]"):
            await self.log("metasploit", "info", line)
        elif line.startswith("[!]"):
            await self.log("metasploit", "warn", line)
        elif line.startswith("[*]"):
            await self.log("metasploit", "info", line)
        elif "Nmap scan report" in line or "open" in line.lower():
            await self.log("metasploit", "info", line)
        # Vuln table output
        elif line.startswith("Vuln") or "host" in line.lower() and "refs" in line.lower():
            await self.log("metasploit", "info", line)

    # =========================================================================
    # FARADAY UPLOAD
    # =========================================================================

    async def _get_faraday_credentials(self) -> Optional[dict]:
        """Get Faraday credentials from the deployment service or k8s secrets."""
        # Try to get from k8s secret
        result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "secret", "faraday-credentials", "-n", "faraday",
             "-o", "jsonpath={.data.admin-password}"],
            timeout=10
        )

        if not result.success or not result.output.strip():
            await self.log(None, "warn", "Could not retrieve Faraday credentials")
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
        """Ensure the Faraday admin user exists (create if missing)."""
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
        # Success if user created or already exists
        output = (result.output or "").lower()
        return result.success or "already" in output or "created" in output

    async def _upload_to_faraday(self, xml_content: str, tool_name: str, creds: dict) -> bool:
        """Upload scan results to Faraday via individual REST API calls.

        Uses faraday-plugins to parse XML, then creates hosts/services/vulns
        one by one via the synchronous REST API (avoids bulk_create which
        requires a Celery worker that isn't running in our deployment).
        """
        await self.log(tool_name, "info", f"Uploading {tool_name} results to Faraday workspace 'pentest'...")

        import tempfile
        import os

        # Map tool names to faraday-plugins plugin names
        plugin_map = {
            "nmap": "nmap",
            "openvas": "openvas",
            "metasploit": "metasploit",
        }
        plugin_name = plugin_map.get(tool_name, tool_name)

        tmp_file = None
        try:
            # Write XML to temp file
            tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False)
            tmp_file.write(xml_content)
            tmp_file.close()

            # Copy XML into Faraday container
            container_xml = f"/tmp/upload-{self.current_scan.id}-{tool_name}.xml"

            # Get the faraday pod name
            pod_result = await self.process_manager.run_command_simple(
                ["kubectl", "get", "pods", "-n", "faraday", "-l", "app.kubernetes.io/name=faraday",
                 "-o", "jsonpath={.items[0].metadata.name}"],
                timeout=10
            )

            if not pod_result.success or not pod_result.output.strip():
                await self.log(tool_name, "warn", "Could not find Faraday pod")
                return False

            pod_name = pod_result.output.strip()

            # kubectl cp the XML file into the container
            cp_result = await self.process_manager.run_command_simple(
                ["kubectl", "cp", tmp_file.name, f"faraday/{pod_name}:{container_xml}",
                 "-c", "faraday"],
                timeout=30
            )

            if not cp_result.success:
                await self.log(tool_name, "warn", f"Failed to copy XML to Faraday container: {cp_result.output}")
                return False

            # Python script that:
            # 1. Logs in to Faraday API
            # 2. Ensures 'pentest' workspace exists
            # 3. Parses XML with faraday-plugins
            # 4. Creates hosts/services/vulns individually via REST API
            #    (bulk_create delegates to Celery which has no worker running)
            upload_script = (
                "import urllib.request, json, http.cookiejar, os, sys\n"
                "BASE = 'http://127.0.0.1:5985'\n"
                "WS = 'pentest'\n"
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
                "# Ensure 'pentest' workspace exists\n"
                "try:\n"
                "    api_get(f'/_api/v3/ws/{WS}')\n"
                "except urllib.error.HTTPError as e:\n"
                "    if e.code == 404:\n"
                "        try:\n"
                "            api_post('/_api/v3/ws', {'name': WS, 'description': 'Automated security scans'})\n"
                "            print('UPLOAD:WS_CREATED:pentest')\n"
                "        except Exception as we:\n"
                "            print(f'UPLOAD:WS_CREATE_FAILED:{we}')\n"
                "            sys.exit(0)\n"
                "\n"
                "# Parse XML with faraday-plugins\n"
                "try:\n"
                "    import importlib\n"
                f"    mod = importlib.import_module('faraday_plugins.plugins.repo.{plugin_name}.plugin')\n"
                "    plugin_cls = None\n"
                "    for name in dir(mod):\n"
                "        obj = getattr(mod, name)\n"
                "        if isinstance(obj, type) and name.endswith('Plugin') and name != 'PluginBase':\n"
                "            plugin_cls = obj\n"
                "            break\n"
                "    if not plugin_cls:\n"
                "        print('UPLOAD:FAILED:Could not find plugin class')\n"
                "        sys.exit(0)\n"
                "    plugin = plugin_cls()\n"
                f"    with open('{container_xml}', 'rb') as f:\n"
                "        xml_data = f.read()\n"
                "    plugin.parseOutputString(xml_data)\n"
                "    bulk_json = json.loads(plugin.get_json())\n"
                "    hosts = bulk_json.get('hosts', [])\n"
                "    print(f'UPLOAD:PARSED:{len(hosts)} hosts')\n"
                "except Exception as e:\n"
                "    print(f'UPLOAD:PARSE_FAILED:{e}')\n"
                "    sys.exit(0)\n"
                "\n"
                "# Create hosts, services, and vulns individually via REST API\n"
                "created_hosts = 0\n"
                "created_services = 0\n"
                "created_vulns = 0\n"
                "errors = 0\n"
                "\n"
                "for h in hosts:\n"
                "    # Create host\n"
                "    host_body = {\n"
                "        'ip': h.get('ip', ''),\n"
                "        'os': h.get('os', ''),\n"
                "        'hostnames': h.get('hostnames', []),\n"
                "        'description': h.get('description', ''),\n"
                "        'mac': h.get('mac', ''),\n"
                "    }\n"
                "    try:\n"
                "        host_resp = api_post(f'/_api/v3/ws/{WS}/hosts', host_body)\n"
                "        host_id = host_resp.get('id')\n"
                "        created_hosts += 1\n"
                "    except urllib.error.HTTPError as e:\n"
                "        body = e.read().decode()\n"
                "        # 409 = host already exists — extract ID from response body\n"
                "        if e.code == 409:\n"
                "            try:\n"
                "                existing = json.loads(body)\n"
                "                host_id = existing.get('object', {}).get('id')\n"
                "                if host_id:\n"
                "                    created_hosts += 1\n"
                "                else:\n"
                "                    errors += 1\n"
                "                    continue\n"
                "            except:\n"
                "                errors += 1\n"
                "                continue\n"
                "        else:\n"
                "            print(f'UPLOAD:HOST_ERROR:{e.code}:{body}')\n"
                "            errors += 1\n"
                "            continue\n"
                "    except Exception as e:\n"
                "        print(f'UPLOAD:HOST_ERROR:{e}')\n"
                "        errors += 1\n"
                "        continue\n"
                "\n"
                "    if not host_id:\n"
                "        continue\n"
                "\n"
                "    # Create services for this host\n"
                "    svc_id_map = {}  # port -> service_id\n"
                "    for svc in h.get('services', []):\n"
                "        port_val = svc.get('port', 0) or 0\n"
                "        svc_body = {\n"
                "            'name': svc.get('name', ''),\n"
                "            'ports': [int(port_val)],\n"
                "            'protocol': svc.get('protocol', 'tcp'),\n"
                "            'status': svc.get('status', 'open'),\n"
                "            'version': svc.get('version', ''),\n"
                "            'description': svc.get('description', ''),\n"
                "            'parent': host_id,\n"
                "            'type': 'Service',\n"
                "        }\n"
                "        try:\n"
                "            svc_resp = api_post(f'/_api/v3/ws/{WS}/services', svc_body)\n"
                "            svc_id_map[int(port_val)] = svc_resp.get('id')\n"
                "            created_services += 1\n"
                "        except urllib.error.HTTPError as se:\n"
                "            if se.code == 409:\n"
                "                try:\n"
                "                    existing_svc = json.loads(se.read().decode())\n"
                "                    svc_id_map[int(port_val)] = existing_svc.get('object', {}).get('id')\n"
                "                    created_services += 1\n"
                "                except:\n"
                "                    errors += 1\n"
                "            else:\n"
                "                errors += 1\n"
                "        except Exception:\n"
                "            errors += 1\n"
                "\n"
                "    # Create host-level vulnerabilities\n"
                "    for vuln in h.get('vulnerabilities', []):\n"
                "        vuln_body = {\n"
                "            'name': vuln.get('name', 'Unknown'),\n"
                "            'desc': vuln.get('desc', ''),\n"
                "            'severity': vuln.get('severity', 'info'),\n"
                "            'refs': vuln.get('refs', []),\n"
                "            'resolution': vuln.get('resolution', ''),\n"
                "            'type': 'Vulnerability',\n"
                "            'parent': host_id,\n"
                "            'parent_type': 'Host',\n"
                "        }\n"
                "        try:\n"
                "            api_post(f'/_api/v3/ws/{WS}/vulns', vuln_body)\n"
                "            created_vulns += 1\n"
                "        except urllib.error.HTTPError:\n"
                "            errors += 1\n"
                "        except Exception:\n"
                "            errors += 1\n"
                "\n"
                "    # Create service-level vulnerabilities\n"
                "    for svc in h.get('services', []):\n"
                "        svc_port = int(svc.get('port', 0) or 0)\n"
                "        svc_id = svc_id_map.get(svc_port)\n"
                "        if not svc_id:\n"
                "            continue\n"
                "        for vuln in svc.get('vulnerabilities', []):\n"
                "            vuln_body = {\n"
                "                'name': vuln.get('name', 'Unknown'),\n"
                "                'desc': vuln.get('desc', ''),\n"
                "                'severity': vuln.get('severity', 'info'),\n"
                "                'refs': vuln.get('refs', []),\n"
                "                'resolution': vuln.get('resolution', ''),\n"
                "                'type': 'Vulnerability',\n"
                "                'parent': svc_id,\n"
                "                'parent_type': 'Service',\n"
                "            }\n"
                "            try:\n"
                "                api_post(f'/_api/v3/ws/{WS}/vulns', vuln_body)\n"
                "                created_vulns += 1\n"
                "            except urllib.error.HTTPError:\n"
                "                errors += 1\n"
                "            except Exception:\n"
                "                errors += 1\n"
                "\n"
                "# Cleanup temp file\n"
                "try:\n"
                f"    os.unlink('{container_xml}')\n"
                "except:\n"
                "    pass\n"
                "\n"
                "total = created_hosts + created_services + created_vulns\n"
                "if total > 0:\n"
                "    print(f'UPLOAD:OK:{created_hosts} hosts, {created_services} services, {created_vulns} vulns ({errors} errors)')\n"
                "else:\n"
                "    print(f'UPLOAD:FAILED:No objects created ({errors} errors)')\n"
            )

            result = await self.process_manager.run_command_simple(
                ["kubectl", "exec", "-n", "faraday", f"pod/{pod_name}", "-c", "faraday",
                 "--", "env", f"F_USER={creds['username']}", f"F_PASS={creds['password']}",
                 "python3", "-c", upload_script],
                timeout=FARADAY_UPLOAD_TIMEOUT
            )

            output = (result.output or "").strip()
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("UPLOAD:OK"):
                    detail = line.split(":", 2)[-1]
                    await self.log(tool_name, "info", f"Uploaded to Faraday: {detail}")
                    return True
                elif line.startswith("UPLOAD:WS_CREATED"):
                    await self.log(tool_name, "info", "Created Faraday workspace 'pentest'")
                elif line.startswith("UPLOAD:PARSED"):
                    await self.log(tool_name, "info", f"Parsed scan results: {line.split(':', 2)[-1]}")
                elif line.startswith("UPLOAD:LOGIN_FAILED"):
                    await self.log(tool_name, "warn", f"Faraday login failed during upload: {line}")
                elif line.startswith("UPLOAD:WS_CREATE_FAILED"):
                    await self.log(tool_name, "warn", f"Failed to create workspace: {line}")
                elif line.startswith("UPLOAD:PARSE_FAILED"):
                    await self.log(tool_name, "warn", f"Failed to parse scan results: {line}")
                elif line.startswith("UPLOAD:HOST_ERROR"):
                    await self.log(tool_name, "warn", f"Error creating host: {line}")
                elif line.startswith("UPLOAD:FAILED"):
                    await self.log(tool_name, "warn", f"Upload failed: {line}")

            return False

        finally:
            if tmp_file and os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

    def _save_to_history(self):
        """Save current scan summary to history."""
        if not self.current_scan:
            return
        scan = self.current_scan
        self.scan_history.append({
            "id": scan.id,
            "target": scan.target,
            "profile": scan.profile.value,
            "status": scan.status.value,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "tools": [
                {
                    "tool": ts.tool.value,
                    "status": ts.status.value,
                    "findings_count": ts.findings_count,
                    "uploaded_to_faraday": ts.uploaded_to_faraday
                }
                for ts in scan.tools
            ]
        })
        # Keep only last 50 scans
        if len(self.scan_history) > 50:
            self.scan_history = self.scan_history[-50:]


# Global scan service instance
_scan_service: Optional[ScanService] = None


def get_scan_service() -> ScanService:
    """Get or create the global scan service instance."""
    global _scan_service
    if _scan_service is None:
        _scan_service = ScanService()
    return _scan_service
