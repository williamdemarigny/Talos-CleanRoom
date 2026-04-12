"""Faraday integration client for uploading scan results.

Provides the FaradayClient class that encapsulates the common Faraday
interaction patterns shared between scan_service (nmap/openvas/metasploit
uploads) and ioc_scan_service (IOC finding uploads).

Uses KubernetesHelper internally for all kubectl operations.
"""

from typing import Optional, Callable, Awaitable, List

from talos_common.services.kubectl_utils import KubernetesHelper
from talos_common.services.process_manager import ProcessManager


# Faraday namespace and label selector constants
FARADAY_NAMESPACE = "faraday"
FARADAY_LABEL_SELECTOR = "app.kubernetes.io/name=faraday"
FARADAY_SECRET_NAME = "faraday-credentials"
FARADAY_SECRET_KEY = "admin-password"
FARADAY_CONTAINER = "faraday"
FARADAY_DEFAULT_USERNAME = "admin"
FARADAY_ADMIN_EMAIL = "admin@knowledgeondemand.net"


class FaradayClient:
    """Client for interacting with the Faraday vulnerability management platform.

    Handles credential retrieval from Kubernetes secrets, admin user
    provisioning, and finding uploads. Uses KubernetesHelper for all
    kubectl operations.

    Example usage::

        client = FaradayClient(process_manager)
        creds = await client.get_credentials()
        if creds:
            await client.ensure_admin(creds)
            pod = await client.get_pod_name()
    """

    def __init__(self, process_manager: ProcessManager):
        self.process_manager = process_manager
        self.k8s = KubernetesHelper(process_manager)

    async def get_credentials(
        self,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> Optional[dict]:
        """Get Faraday credentials from the k8s secret.

        Retrieves and base64-decodes the admin password from the
        ``faraday-credentials`` secret in the ``faraday`` namespace.

        Args:
            log_callback: Optional async callback ``(level, message)`` for
                logging. If provided, warnings are emitted when credentials
                cannot be retrieved.

        Returns:
            Dict with ``username`` and ``password`` keys, or None if
            credentials are unavailable.
        """
        password = await self.k8s.get_secret(
            FARADAY_NAMESPACE, FARADAY_SECRET_NAME, FARADAY_SECRET_KEY
        )

        if not password:
            if log_callback:
                await log_callback("warn", "Could not retrieve Faraday credentials")
            return None

        return {
            "username": FARADAY_DEFAULT_USERNAME,
            "password": password
        }

    async def get_pod_name(self) -> Optional[str]:
        """Get the Faraday pod name.

        Returns:
            The pod name string, or None if not found.
        """
        return await self.k8s.get_pod_name(
            FARADAY_NAMESPACE, FARADAY_LABEL_SELECTOR
        )

    async def ensure_admin(
        self,
        creds: dict,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> bool:
        """Ensure the Faraday admin user exists (create if missing).

        Runs ``faraday-manage create-superuser`` inside the Faraday pod.
        The command succeeds silently if the user already exists.

        Args:
            creds: Dict with ``username`` and ``password`` keys.
            log_callback: Optional async callback for logging.

        Returns:
            True if the admin user exists or was created, False on error.
        """
        pod_name = await self.get_pod_name()
        if not pod_name:
            return False

        result = await self.k8s.exec_in_pod(
            namespace=FARADAY_NAMESPACE,
            pod_name=pod_name,
            command=[
                "faraday-manage", "create-superuser",
                "--username", creds["username"],
                "--email", FARADAY_ADMIN_EMAIL,
                "--password", creds["password"]
            ],
            container=FARADAY_CONTAINER,
            timeout=30
        )

        # Success if user created or already exists
        output = (result.output or "").lower()
        return result.success or "already" in output or "created" in output

    async def upload_ioc_findings(
        self,
        findings_data: list,
        target: str,
        scan_id: str,
        creds: dict,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        timeout: float = 120
    ) -> bool:
        """Upload IOC findings to Faraday via REST API.

        Runs a Python script inside the Faraday container that creates
        a host for the target and vulns for each IOC finding. This is
        the pattern used by ioc_scan_service.

        Args:
            findings_data: List of finding dicts (severity, score,
                file_path, rule_name, description, etc.).
            target: Target IP or hostname.
            scan_id: Scan identifier for tagging.
            creds: Faraday credentials dict.
            log_callback: Optional async callback for logging.
            timeout: Upload timeout in seconds.

        Returns:
            True if findings were uploaded successfully, False otherwise.
        """
        if log_callback:
            await log_callback("info", "Uploading IOC findings to Faraday workspace 'pentest'...")

        pod_name = await self.get_pod_name()
        if not pod_name:
            if log_callback:
                await log_callback("warn", "Could not find Faraday pod")
            return False

        import json
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

        result = await self.k8s.exec_in_pod(
            namespace=FARADAY_NAMESPACE,
            pod_name=pod_name,
            command=["python3", "-c", upload_script],
            container=FARADAY_CONTAINER,
            env={
                "F_USER": creds["username"],
                "F_PASS": creds["password"],
                "FINDINGS_JSON": findings_json,
            },
            timeout=timeout
        )

        output = (result.output or "").strip()
        return self._parse_upload_output(output, log_callback)

    async def upload_scan_results(
        self,
        xml_content: str,
        tool_name: str,
        creds: dict,
        scan_id: str = "",
        scan_profile: str = "",
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        timeout: float = 300
    ) -> bool:
        """Upload scan results (nmap/openvas/metasploit XML) to Faraday.

        Copies the XML file into the Faraday container, then runs a
        Python script that parses it with faraday-plugins (or direct XML
        parsing for OpenVAS) and creates hosts/services/vulns via the
        Faraday REST API.

        This is a complex operation with a large in-container script.
        The scan_service.py ``_upload_to_faraday`` method contains the
        full upload script which is tool-specific. This method provides
        the shared setup (credential retrieval, pod discovery, XML copy)
        but the actual upload script remains in scan_service.py because
        it is tightly coupled to the scan tool's output format.

        For the common pre-upload steps (get creds, ensure admin, get pod),
        use ``get_credentials()``, ``ensure_admin()``, and ``get_pod_name()``
        directly.

        Args:
            xml_content: The XML scan results as a string.
            tool_name: Tool name (nmap, openvas, metasploit).
            creds: Faraday credentials dict.
            scan_id: Scan identifier for tagging.
            scan_profile: Scan profile name for tagging.
            log_callback: Optional async callback for logging.
            timeout: Upload timeout in seconds.

        Returns:
            True if upload succeeded, False otherwise.
        """
        # This method is intentionally left as a thin wrapper.
        # The actual upload script logic is complex, tool-specific, and
        # maintained in scan_service.py's _upload_to_faraday method.
        # Services should use get_credentials(), ensure_admin(), and
        # get_pod_name() for the common pre-upload steps.
        raise NotImplementedError(
            "Full scan result upload is tool-specific. "
            "Use get_credentials(), ensure_admin(), and get_pod_name() "
            "for shared pre-upload steps, then handle the tool-specific "
            "upload script in the service itself."
        )

    @staticmethod
    def _parse_upload_output(
        output: str,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> bool:
        """Parse the structured output from the in-container upload script.

        The upload scripts emit lines prefixed with ``UPLOAD:`` that
        indicate success, failure, or progress. This method parses those
        lines and returns whether the upload was successful.

        Note: This is a sync helper that returns a bool. Log callbacks
        are not awaited here — callers that need logging should parse
        the output themselves (as the existing services do).

        Args:
            output: Raw stdout from the upload script.
            log_callback: Not used in this static method (kept for
                signature compatibility). Callers handle logging.

        Returns:
            True if any ``UPLOAD:OK`` line was found, False otherwise.
        """
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("UPLOAD:OK"):
                return True
        return False

    async def parse_and_log_upload_output(
        self,
        output: str,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> bool:
        """Parse upload output with logging via async callback.

        Processes each ``UPLOAD:`` prefixed line from the in-container
        script and logs appropriate messages.

        Args:
            output: Raw stdout from the upload script.
            log_callback: Async callback ``(level, message)`` for logging.

        Returns:
            True if the upload was successful, False otherwise.
        """
        success = False
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.startswith("UPLOAD:OK"):
                detail = line.split(":", 2)[-1]
                if log_callback:
                    await log_callback("info", f"Uploaded to Faraday: {detail}")
                success = True
            elif line.startswith("UPLOAD:FAILED"):
                detail = line.split(":", 2)[-1]
                if log_callback:
                    await log_callback("warn", f"Faraday upload issue: {detail}")
            elif line.startswith("UPLOAD:LOGIN_FAILED"):
                detail = line.split(":", 2)[-1]
                if log_callback:
                    await log_callback("error", f"Faraday login failed: {detail}")
            elif line.startswith("UPLOAD:WS_CREATED"):
                if log_callback:
                    await log_callback("info", "Created Faraday workspace 'pentest'")
            elif line.startswith("UPLOAD:PARSED"):
                if log_callback:
                    await log_callback("info", f"Parsed scan results: {line.split(':', 2)[-1]}")
            elif line.startswith("UPLOAD:SVC_"):
                if log_callback:
                    await log_callback("info", f"Service names: {line.split(':', 2)[-1]}")
            elif line.startswith("UPLOAD:WS_CREATE_FAILED"):
                if log_callback:
                    await log_callback("warn", f"Failed to create workspace: {line}")
            elif line.startswith("UPLOAD:PARSE_FAILED"):
                if log_callback:
                    await log_callback("warn", f"Failed to parse scan results: {line}")
            elif line.startswith("UPLOAD:HOST_ERROR"):
                if log_callback:
                    await log_callback("warn", f"Error creating host: {line}")
            elif line.startswith("UPLOAD:ERR"):
                detail = line.split(":", 2)[-1] if ":" in line[11:] else line
                if log_callback:
                    await log_callback("warn", f"API error: {detail}")

        return success
