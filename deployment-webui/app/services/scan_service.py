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
METASPLOIT_TIMEOUT = 1800      # 30 min for Metasploit
FARADAY_UPLOAD_TIMEOUT = 60    # 1 min for Faraday upload

# Nmap flags per profile
NMAP_PROFILES = {
    ScanProfile.QUICK: ["-sn", "--top-ports", "100"],
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
            await self.log_callback(entry)

    async def _update_tool_state(self, tool: ScanTool, **kwargs):
        """Update a tool's state and notify via callback."""
        if not self.current_scan:
            return
        for ts in self.current_scan.tools:
            if ts.tool == tool:
                for key, value in kwargs.items():
                    setattr(ts, key, value)
                if self.tool_callback:
                    await self.tool_callback(ts)
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

            # Get Faraday credentials for later upload
            faraday_creds = await self._get_faraday_credentials()

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

        # Use kubectl run to create an ephemeral nmap pod
        # --attach waits for pod completion and streams stdout (no stdin needed)
        # --rm auto-deletes the pod after it finishes
        result = await self.process_manager.run_command_simple(
            ["kubectl", "run", pod_name,
             "--image=instrumentisto/nmap:latest",
             "--rm", "--attach", "--restart=Never",
             "--namespace=default",
             "--", "nmap"] + flags + ["-oX", "-", target],
            timeout=timeout
        )

        # Clean up pod if it wasn't auto-removed
        await self.process_manager.run_command_simple(
            ["kubectl", "delete", "pod", pod_name, "--namespace=default",
             "--ignore-not-found", "--grace-period=0", "--force"],
            timeout=15
        )

        if not result.success and "TIMEOUT" in (result.output or ""):
            await self.log("nmap", "error", f"Nmap scan timed out after {timeout}s")
            return None

        output = result.output or ""

        # Extract XML content from output (may contain kubectl preamble)
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
            for line in output.split("\n")[-20:]:
                line = line.strip()
                if line:
                    await self.log("nmap", "info", f"  {line}")
            await self.log("nmap", "warn", "Could not extract XML from Nmap output")
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
            ["kubectl", "get", "secret", "greenbone-credentials", "-n", "openvas",
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

    async def _run_metasploit_scan(self, target: str, profile: ScanProfile) -> Optional[str]:
        """Run a Metasploit scan via resource script."""
        scan_id = self.current_scan.id

        # Build nmap flags for db_nmap based on profile
        nmap_flags = {
            ScanProfile.QUICK: "-sn --top-ports 100",
            ScanProfile.STANDARD: "-sV -sC",
            ScanProfile.THOROUGH: "-sV -sC -p- -A",
        }.get(profile, "-sV -sC")

        xml_path = f"/tmp/msf-scan-{scan_id}.xml"
        rc_path = f"/tmp/scan-{scan_id}.rc"

        await self.log("metasploit", "info", f"Preparing Metasploit resource script...")

        # Write resource script into the container
        rc_content = (
            f"db_nmap {nmap_flags} {target}\\n"
            f"db_export -f xml {xml_path}\\n"
            f"exit\\n"
        )

        write_rc = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "bash", "-c", f"printf '{rc_content}' > {rc_path}"],
            timeout=15
        )

        if not write_rc.success:
            await self.log("metasploit", "error", f"Failed to write resource script: {write_rc.output}")
            return None

        await self.log("metasploit", "info", f"Running msfconsole with db_nmap {nmap_flags} {target}...")

        # Run msfconsole with the resource script
        result = await self.process_manager.run_command(
            ["kubectl", "exec", "-n", "metasploit", "deployment/metasploit",
             "-c", "metasploit", "--",
             "./msfconsole", "-q", "-r", rc_path],
            on_output=lambda line: self._log_msf_line(line),
            timeout=METASPLOIT_TIMEOUT
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
                    ts.findings_count = host_count
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
        if line.startswith("=") or line.startswith("[*] ===") or "metasploit" in line.lower() and "http" not in line:
            return
        # Log meaningful output
        if line.startswith("[*]") or line.startswith("[+]") or line.startswith("[-]") or line.startswith("[!]"):
            await self.log("metasploit", "info", line)
        elif "Nmap scan report" in line or "open" in line.lower():
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
                "username": "faraday",
                "password": decode_result.output.strip()
            }

        return None

    async def _upload_to_faraday(self, xml_content: str, tool_name: str, creds: dict) -> bool:
        """Upload scan results to Faraday via its REST API."""
        await self.log(tool_name, "info", f"Uploading {tool_name} results to Faraday workspace 'pentest'...")

        # Python script to upload report via Faraday API
        # Runs inside the Faraday container using stdlib only
        upload_script = (
            "import urllib.request, json, http.cookiejar, os, sys, io\n"
            "cj = http.cookiejar.CookieJar()\n"
            "opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))\n"
            "# Login\n"
            "try:\n"
            "    data = json.dumps({'email': os.environ['F_USER'], 'password': os.environ['F_PASS']}).encode()\n"
            "    req = urllib.request.Request('http://127.0.0.1:5985/_api/login', method='POST',\n"
            "        headers={'Content-Type': 'application/json'}, data=data)\n"
            "    resp = opener.open(req)\n"
            "    login = json.loads(resp.read().decode())\n"
            "    csrf = login['response']['csrf_token']\n"
            "except Exception as e:\n"
            "    print(f'UPLOAD:LOGIN_FAILED:{e}')\n"
            "    sys.exit(0)\n"
            "# Upload report\n"
            "try:\n"
            "    xml_data = sys.stdin.buffer.read()\n"
            "    boundary = '----FormBoundary7MA4YWxkTrZu0gW'\n"
            "    body = (\n"
            "        f'--{boundary}\\r\\n'\n"
            "        f'Content-Disposition: form-data; name=\"file\"; filename=\"report.xml\"\\r\\n'\n"
            "        f'Content-Type: application/xml\\r\\n'\n"
            "        f'\\r\\n'\n"
            "    ).encode() + xml_data + f'\\r\\n--{boundary}--\\r\\n'.encode()\n"
            "    req2 = urllib.request.Request(\n"
            "        'http://127.0.0.1:5985/_api/v3/ws/pentest/upload_report',\n"
            "        method='POST',\n"
            "        headers={\n"
            "            'Content-Type': f'multipart/form-data; boundary={boundary}',\n"
            "            'X-CSRFToken': csrf\n"
            "        },\n"
            "        data=body\n"
            "    )\n"
            "    resp2 = opener.open(req2)\n"
            "    result = resp2.read().decode()\n"
            "    print(f'UPLOAD:OK:{result}')\n"
            "except urllib.error.HTTPError as e:\n"
            "    body = e.read().decode()\n"
            "    print(f'UPLOAD:HTTP_ERROR:{e.code}:{body}')\n"
            "except Exception as e:\n"
            "    print(f'UPLOAD:FAILED:{e}')\n"
        )

        # Pipe the XML content via stdin to the upload script running in the Faraday container
        # We write the XML to a temp file first, then use kubectl exec with stdin redirect
        import tempfile
        import os

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

            # Now run the upload script, reading the XML from the container filesystem
            upload_with_file_script = (
                "import urllib.request, json, http.cookiejar, os, sys\n"
                "cj = http.cookiejar.CookieJar()\n"
                "opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))\n"
                "try:\n"
                "    data = json.dumps({'email': os.environ['F_USER'], 'password': os.environ['F_PASS']}).encode()\n"
                "    req = urllib.request.Request('http://127.0.0.1:5985/_api/login', method='POST',\n"
                "        headers={'Content-Type': 'application/json'}, data=data)\n"
                "    resp = opener.open(req)\n"
                "    login = json.loads(resp.read().decode())\n"
                "    csrf = login['response']['csrf_token']\n"
                "except Exception as e:\n"
                "    print(f'UPLOAD:LOGIN_FAILED:{e}')\n"
                "    sys.exit(0)\n"
                "try:\n"
                f"    xml_path = '{container_xml}'\n"
                "    with open(xml_path, 'rb') as f:\n"
                "        xml_data = f.read()\n"
                "    boundary = '----FormBoundary7MA4YWxkTrZu0gW'\n"
                "    body = (\n"
                "        f'--{boundary}\\r\\n'\n"
                "        f'Content-Disposition: form-data; name=\"file\"; filename=\"report.xml\"\\r\\n'\n"
                "        f'Content-Type: application/xml\\r\\n'\n"
                "        f'\\r\\n'\n"
                "    ).encode() + xml_data + f'\\r\\n--{boundary}--\\r\\n'.encode()\n"
                "    req2 = urllib.request.Request(\n"
                "        'http://127.0.0.1:5985/_api/v3/ws/pentest/upload_report',\n"
                "        method='POST',\n"
                "        headers={\n"
                "            'Content-Type': f'multipart/form-data; boundary={boundary}',\n"
                "            'X-CSRFToken': csrf\n"
                "        },\n"
                "        data=body\n"
                "    )\n"
                "    resp2 = opener.open(req2)\n"
                "    result = resp2.read().decode()\n"
                "    print(f'UPLOAD:OK:{result}')\n"
                "except urllib.error.HTTPError as e:\n"
                "    body = e.read().decode()\n"
                "    print(f'UPLOAD:HTTP_ERROR:{e.code}:{body}')\n"
                "except Exception as e:\n"
                "    print(f'UPLOAD:FAILED:{e}')\n"
                "finally:\n"
                f"    import os; os.unlink('{container_xml}') if os.path.exists('{container_xml}') else None\n"
            )

            result = await self.process_manager.run_command_simple(
                ["kubectl", "exec", "-n", "faraday", f"pod/{pod_name}", "-c", "faraday",
                 "--", "env", f"F_USER={creds['username']}", f"F_PASS={creds['password']}",
                 "python3", "-c", upload_with_file_script],
                timeout=FARADAY_UPLOAD_TIMEOUT
            )

            output = (result.output or "").strip()
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("UPLOAD:OK"):
                    await self.log(tool_name, "info", f"Successfully uploaded {tool_name} results to Faraday")
                    return True
                elif line.startswith("UPLOAD:LOGIN_FAILED"):
                    await self.log(tool_name, "warn", f"Faraday login failed during upload: {line}")
                elif line.startswith("UPLOAD:HTTP_ERROR"):
                    await self.log(tool_name, "warn", f"Faraday upload HTTP error: {line}")
                elif line.startswith("UPLOAD:FAILED"):
                    await self.log(tool_name, "warn", f"Faraday upload failed: {line}")

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
