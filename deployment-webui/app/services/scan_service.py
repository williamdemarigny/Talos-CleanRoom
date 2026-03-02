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
# OpenVAS timeouts per profile (seconds) — outer safety net for asyncio.wait_for.
# GMP scripts self-terminate on stale progress (30min no change), so these are generous ceilings.
OPENVAS_TIMEOUTS = {
    ScanProfile.QUICK: 7500,        # 2h 5min — host discovery finishes fast
    ScanProfile.STANDARD: 28800,    # 8h — full-and-fast on large subnets
    ScanProfile.THOROUGH: 50400,    # 14h — full-and-deep, many hosts
    ScanProfile.CUSTOM: 50400,      # 14h — custom family scans may be thorough
}
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

# =============================================================================
# Metasploit Module Catalog — single source of truth for all profiles
# =============================================================================
MSF_MODULE_CATALOG = [
    # --- Critical CVEs (included in standard + thorough) ---
    {
        "id": "auxiliary/scanner/smb/smb_ms17_010",
        "name": "EternalBlue (MS17-010)",
        "category": "Critical CVEs",
        "description": "SMB Remote Code Execution check",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/smb/smb_ms08_067",
        "name": "Conficker (MS08-067)",
        "category": "Critical CVEs",
        "description": "SMB Remote Code Execution check",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/rdp/cve_2019_0708_bluekeep",
        "name": "BlueKeep (CVE-2019-0708)",
        "category": "Critical CVEs",
        "description": "RDP Remote Code Execution check",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/ssl/openssl_heartbleed",
        "name": "Heartbleed (CVE-2014-0160)",
        "category": "Critical CVEs",
        "description": "OpenSSL memory disclosure",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/http/log4shell_scanner",
        "name": "Log4Shell (CVE-2021-44228)",
        "category": "Critical CVEs",
        "description": "Apache Log4j Remote Code Execution",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/http/apache_mod_cgi_bash_env",
        "name": "Shellshock (CVE-2014-6271)",
        "category": "Critical CVEs",
        "description": "Bash environment variable injection via CGI",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/http/ms15_034_http_sys_memory_dump",
        "name": "HTTP.sys (MS15-034)",
        "category": "Critical CVEs",
        "description": "IIS HTTP.sys memory disclosure",
        "profiles": ["standard", "thorough"],
    },
    # --- Service Detection (included in standard + thorough) ---
    {
        "id": "auxiliary/scanner/smb/smb_version",
        "name": "SMB Version",
        "category": "Service Detection",
        "description": "SMB protocol version fingerprint",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/ssh/ssh_version",
        "name": "SSH Version",
        "category": "Service Detection",
        "description": "SSH protocol version fingerprint",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/http/http_version",
        "name": "HTTP Version",
        "category": "Service Detection",
        "description": "HTTP server fingerprint",
        "profiles": ["standard", "thorough"],
    },
    {
        "id": "auxiliary/scanner/ftp/anonymous",
        "name": "FTP Anonymous",
        "category": "Service Detection",
        "description": "FTP anonymous access check",
        "profiles": ["standard", "thorough"],
    },
    # --- Extended SMB (thorough only) ---
    {
        "id": "auxiliary/scanner/smb/smb_enumshares",
        "name": "SMB Share Enumeration",
        "category": "Extended SMB",
        "description": "Enumerate SMB shares",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/smb/smb_enumusers",
        "name": "SMB User Enumeration",
        "category": "Extended SMB",
        "description": "Enumerate SMB users",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/smb/pipe_auditor",
        "name": "SMB Pipe Auditor",
        "category": "Extended SMB",
        "description": "SMB named pipe auditing",
        "profiles": ["thorough"],
    },
    # --- Extended RDP (thorough only) ---
    {
        "id": "auxiliary/scanner/rdp/rdp_scanner",
        "name": "RDP Scanner",
        "category": "Extended RDP",
        "description": "RDP service detection",
        "profiles": ["thorough"],
    },
    # --- Extended SSH (thorough only) ---
    {
        "id": "auxiliary/scanner/ssh/ssh_enumusers",
        "name": "SSH User Enumeration",
        "category": "Extended SSH",
        "description": "Enumerate SSH users via wordlist",
        "profiles": ["thorough"],
        "extra_opts": {"USER_FILE": "/opt/metasploit-framework/data/wordlists/unix_users.txt"},
    },
    # --- HTTP/Web (thorough only) ---
    {
        "id": "auxiliary/scanner/http/title",
        "name": "HTTP Title",
        "category": "HTTP/Web",
        "description": "HTTP page title extraction",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/dir_scanner",
        "name": "Directory Scanner",
        "category": "HTTP/Web",
        "description": "HTTP directory brute-force",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/robots_txt",
        "name": "Robots.txt",
        "category": "HTTP/Web",
        "description": "robots.txt discovery",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/http_put",
        "name": "HTTP PUT",
        "category": "HTTP/Web",
        "description": "HTTP PUT method test",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/tomcat_mgr_login",
        "name": "Tomcat Manager Login",
        "category": "HTTP/Web",
        "description": "Tomcat default credentials check",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/wordpress_scanner",
        "name": "WordPress Scanner",
        "category": "HTTP/Web",
        "description": "WordPress detection and enumeration",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/jenkins_enum",
        "name": "Jenkins Enum",
        "category": "HTTP/Web",
        "description": "Jenkins open dashboard detection",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/http/webdav_scanner",
        "name": "WebDAV Scanner",
        "category": "HTTP/Web",
        "description": "WebDAV detection",
        "profiles": ["thorough"],
    },
    # --- SSL/TLS (thorough only) ---
    {
        "id": "auxiliary/scanner/ssl/ssl_version",
        "name": "SSL/TLS Version",
        "category": "SSL/TLS",
        "description": "SSL/TLS version and cipher analysis",
        "profiles": ["thorough"],
    },
    # --- FTP (thorough only) ---
    {
        "id": "auxiliary/scanner/ftp/ftp_version",
        "name": "FTP Version",
        "category": "FTP",
        "description": "FTP version fingerprint",
        "profiles": ["thorough"],
    },
    # --- Email (thorough only) ---
    {
        "id": "auxiliary/scanner/smtp/smtp_version",
        "name": "SMTP Version",
        "category": "Email",
        "description": "SMTP server version detection",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/smtp/smtp_relay",
        "name": "SMTP Open Relay",
        "category": "Email",
        "description": "Open SMTP relay check",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/pop3/pop3_version",
        "name": "POP3 Version",
        "category": "Email",
        "description": "POP3 server version detection",
        "profiles": ["thorough"],
    },
    # --- Database (thorough only) ---
    {
        "id": "auxiliary/scanner/mysql/mysql_version",
        "name": "MySQL Version",
        "category": "Database",
        "description": "MySQL version detection",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/postgres/postgres_version",
        "name": "PostgreSQL Version",
        "category": "Database",
        "description": "PostgreSQL version detection",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/mssql/mssql_ping",
        "name": "MSSQL Discovery",
        "category": "Database",
        "description": "MSSQL instance discovery",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/mongodb/mongodb_login",
        "name": "MongoDB Login",
        "category": "Database",
        "description": "MongoDB unauthenticated access check",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/redis/redis_server",
        "name": "Redis Server",
        "category": "Database",
        "description": "Redis open access check",
        "profiles": ["thorough"],
    },
    # --- Network Infrastructure (thorough only) ---
    {
        "id": "auxiliary/scanner/telnet/telnet_version",
        "name": "Telnet Version",
        "category": "Network Infrastructure",
        "description": "Telnet service detection",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/snmp/snmp_enum",
        "name": "SNMP Enumeration",
        "category": "Network Infrastructure",
        "description": "SNMP community string enumeration",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/netbios/nbname",
        "name": "NetBIOS Name",
        "category": "Network Infrastructure",
        "description": "NetBIOS name resolution",
        "profiles": ["thorough"],
    },
    {
        "id": "auxiliary/scanner/discovery/udp_sweep",
        "name": "UDP Sweep",
        "category": "Network Infrastructure",
        "description": "UDP service discovery",
        "profiles": ["thorough"],
    },
    # --- Remote Access (thorough only) ---
    {
        "id": "auxiliary/scanner/vnc/vnc_none_auth",
        "name": "VNC No-Auth",
        "category": "Remote Access",
        "description": "VNC no-authentication check",
        "profiles": ["thorough"],
    },
    # =================================================================
    # Additional modules (custom profile only — not in any preset)
    # =================================================================
    # --- Additional CVE Scanners ---
    {
        "id": "auxiliary/scanner/http/exchange_proxylogon",
        "name": "ProxyLogon (CVE-2021-26855)",
        "category": "Additional CVEs",
        "description": "Exchange Server SSRF to RCE",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/apache_normalize_path",
        "name": "Apache Path Traversal (CVE-2021-41773)",
        "category": "Additional CVEs",
        "description": "Apache HTTP Server path traversal",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/citrix_dir_traversal",
        "name": "Citrix ADC Traversal (CVE-2019-19781)",
        "category": "Additional CVEs",
        "description": "Citrix ADC/Gateway directory traversal",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/apache_optionsbleed",
        "name": "Optionsbleed (CVE-2017-9798)",
        "category": "Additional CVEs",
        "description": "Apache OPTIONS memory leak",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/vmware/vmauthd_version",
        "name": "VMware Auth Daemon",
        "category": "Additional CVEs",
        "description": "VMware authentication daemon detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/ipmi/ipmi_cipher_zero",
        "name": "IPMI Cipher Zero",
        "category": "Additional CVEs",
        "description": "IPMI cipher zero authentication bypass",
        "profiles": [],
    },
    # --- Credential Checks ---
    {
        "id": "auxiliary/scanner/smb/smb_login",
        "name": "SMB Login",
        "category": "Credential Checks",
        "description": "SMB default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/ssh/ssh_login",
        "name": "SSH Login",
        "category": "Credential Checks",
        "description": "SSH default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/ftp/ftp_login",
        "name": "FTP Login",
        "category": "Credential Checks",
        "description": "FTP default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/mysql/mysql_login",
        "name": "MySQL Login",
        "category": "Credential Checks",
        "description": "MySQL default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/postgres/postgres_login",
        "name": "PostgreSQL Login",
        "category": "Credential Checks",
        "description": "PostgreSQL default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/mssql/mssql_login",
        "name": "MSSQL Login",
        "category": "Credential Checks",
        "description": "MSSQL default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/vnc/vnc_login",
        "name": "VNC Login",
        "category": "Credential Checks",
        "description": "VNC default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/telnet/telnet_login",
        "name": "Telnet Login",
        "category": "Credential Checks",
        "description": "Telnet default/weak credential check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/snmp/snmp_login",
        "name": "SNMP Login",
        "category": "Credential Checks",
        "description": "SNMP community string brute-force",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/winrm/winrm_login",
        "name": "WinRM Login",
        "category": "Credential Checks",
        "description": "WinRM default/weak credential check",
        "profiles": [],
    },
    # --- Additional Web Application ---
    {
        "id": "auxiliary/scanner/http/joomla_version",
        "name": "Joomla Detection",
        "category": "Additional Web",
        "description": "Joomla CMS version detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/drupal_views_user_enum",
        "name": "Drupal User Enum",
        "category": "Additional Web",
        "description": "Drupal views user enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/jboss_vulnscan",
        "name": "JBoss Vuln Scan",
        "category": "Additional Web",
        "description": "JBoss application server vulnerability scan",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/verb_auth_bypass",
        "name": "HTTP Verb Tampering",
        "category": "Additional Web",
        "description": "HTTP verb tampering authentication bypass",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/backup_file",
        "name": "Backup File Discovery",
        "category": "Additional Web",
        "description": "Common backup file detection (.bak, .old, etc)",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/trace_axd",
        "name": "ASP.NET Trace",
        "category": "Additional Web",
        "description": "ASP.NET trace.axd information disclosure",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/files_dir",
        "name": "Sensitive File Discovery",
        "category": "Additional Web",
        "description": "Common sensitive file and directory detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/cert",
        "name": "SSL Certificate Info",
        "category": "Additional Web",
        "description": "SSL/TLS certificate information extraction",
        "profiles": [],
    },
    # --- Windows / Active Directory ---
    {
        "id": "auxiliary/scanner/smb/smb_lookupsid",
        "name": "SMB SID Lookup",
        "category": "Windows/AD",
        "description": "SID enumeration for user discovery",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/smb/smb2",
        "name": "SMBv2 Detection",
        "category": "Windows/AD",
        "description": "SMBv2 protocol support detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/winrm/winrm_auth_methods",
        "name": "WinRM Auth Methods",
        "category": "Windows/AD",
        "description": "WinRM authentication method enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/dcerpc/endpoint_mapper",
        "name": "DCERPC Endpoint Mapper",
        "category": "Windows/AD",
        "description": "DCERPC endpoint mapper enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/dcerpc/management",
        "name": "DCERPC Management",
        "category": "Windows/AD",
        "description": "DCERPC management interface detection",
        "profiles": [],
    },
    # --- Additional Network Infrastructure ---
    {
        "id": "auxiliary/scanner/dns/dns_amp",
        "name": "DNS Amplification",
        "category": "Additional Network",
        "description": "DNS amplification vulnerability check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/ntp/ntp_monlist",
        "name": "NTP Monlist",
        "category": "Additional Network",
        "description": "NTP monlist amplification check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/ipmi/ipmi_version",
        "name": "IPMI Version",
        "category": "Additional Network",
        "description": "IPMI version and capability detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/nfs/nfsmount",
        "name": "NFS Exports",
        "category": "Additional Network",
        "description": "NFS export enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/sip/enumerator",
        "name": "SIP Enumerator",
        "category": "Additional Network",
        "description": "SIP user/extension enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/rsync/modules_list",
        "name": "Rsync Modules",
        "category": "Additional Network",
        "description": "Rsync module listing",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/elasticsearch/indices_enum",
        "name": "Elasticsearch Indices",
        "category": "Additional Network",
        "description": "Elasticsearch index enumeration",
        "profiles": [],
    },
    # --- Additional Web Discovery ---
    {
        "id": "auxiliary/scanner/http/open_proxy",
        "name": "Open Proxy",
        "category": "Additional Web",
        "description": "Open HTTP proxy detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/sqli_simple",
        "name": "SQL Injection Check",
        "category": "Additional Web",
        "description": "Simple SQL injection detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/iis_shortname_scanner",
        "name": "IIS Short Name",
        "category": "Additional Web",
        "description": "IIS 8.3 short filename enumeration",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/svn_scanner",
        "name": "SVN Repository",
        "category": "Additional Web",
        "description": "Exposed SVN repository detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/git_scanner",
        "name": "Git Repository",
        "category": "Additional Web",
        "description": "Exposed .git directory detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/http/owa_login",
        "name": "Outlook Web Access",
        "category": "Additional Web",
        "description": "OWA login page detection",
        "profiles": [],
    },
    # --- Additional Service Discovery ---
    {
        "id": "auxiliary/scanner/misc/java_rmi_server",
        "name": "Java RMI",
        "category": "Additional Network",
        "description": "Java RMI registry detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/x11/open_x11",
        "name": "Open X11",
        "category": "Additional Network",
        "description": "Open X11 display detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/rservices/rlogin_login",
        "name": "rlogin Access",
        "category": "Additional Network",
        "description": "rlogin unauthenticated access check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/rservices/rsh_login",
        "name": "rsh Access",
        "category": "Additional Network",
        "description": "rsh unauthenticated access check",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/llmnr/query",
        "name": "LLMNR Query",
        "category": "Additional Network",
        "description": "LLMNR poisoning target detection",
        "profiles": [],
    },
    {
        "id": "auxiliary/scanner/mdns/query",
        "name": "mDNS Query",
        "category": "Additional Network",
        "description": "mDNS service discovery",
        "profiles": [],
    },
    # --- IPMI Extended ---
    {
        "id": "auxiliary/scanner/ipmi/ipmi_dumphashes",
        "name": "IPMI Hash Dump",
        "category": "Additional Network",
        "description": "IPMI password hash extraction",
        "profiles": [],
    },
    # --- Printer/IoT ---
    {
        "id": "auxiliary/scanner/printer/printer_list_volumes",
        "name": "Printer Volumes",
        "category": "Additional Network",
        "description": "Network printer volume enumeration",
        "profiles": [],
    },
]


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

    def get_module_catalog(self) -> list:
        """Return the Metasploit module catalog for custom profile selection."""
        return MSF_MODULE_CATALOG

    # ----- OpenVAS runtime discovery (configs & NVT families) ----------------

    _openvas_configs_cache: Optional[list] = None
    _openvas_families_cache: Optional[list] = None

    async def _get_openvas_password(self) -> Optional[str]:
        """Retrieve and decode the OpenVAS admin password from k8s secret."""
        cred_result = await self.process_manager.run_command_simple(
            ["kubectl", "get", "secret", "openvas-credentials", "-n", "openvas",
             "-o", "jsonpath={.data.admin-password}"],
            timeout=10
        )
        if not cred_result.success or not cred_result.output.strip():
            return None
        password_b64 = cred_result.output.strip()
        decode_result = await self.process_manager.run_command_simple(
            ["bash", "-c", f"echo '{password_b64}' | base64 -d"],
            timeout=5
        )
        return decode_result.output.strip() if decode_result.success else None

    async def get_openvas_configs(self) -> list:
        """Query available OpenVAS scan configs from GVM via GMP."""
        if self._openvas_configs_cache is not None:
            return self._openvas_configs_cache

        password = await self._get_openvas_password()
        if not password:
            return []

        script = '''
import socket, os, sys
import xml.etree.ElementTree as ET

SOCK_PATH = "/run/gvmd/gvmd.sock"
PASSWORD = os.environ.get("GMP_PASSWORD", "")

def send_gmp(sock, xml_str):
    sock.sendall(xml_str.encode("utf-8"))
    response = b""
    while True:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk
            text = response.decode("utf-8", errors="replace")
            for tag in ["authenticate_response", "get_configs_response"]:
                if f"</{tag}>" in text:
                    return text
        except socket.timeout:
            break
    return response.decode("utf-8", errors="replace")

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect(SOCK_PATH)

    auth_xml = f\'<authenticate><credentials><username>admin</username><password>{PASSWORD}</password></credentials></authenticate>\'
    resp = send_gmp(sock, auth_xml)

    resp = send_gmp(sock, \'<get_configs/>\')
    root = ET.fromstring(resp)
    for cfg in root.findall("config"):
        cfg_id = cfg.attrib.get("id", "")
        name = cfg.findtext("name", "")
        # Skip the "empty" base configs used internally
        if name and cfg_id:
            print(f"CONFIG:{cfg_id}:{name}")

    sock.close()
except Exception as e:
    print(f"ERROR:{e}", file=sys.stderr)
    sys.exit(1)
'''

        result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "openvas", "deployment/greenbone", "-c", "gvmd",
             "--", "env", f"GMP_PASSWORD={password}",
             "python3", "-c", script],
            timeout=30
        )

        configs = []
        if result.success and result.output:
            for line in result.output.strip().split("\n"):
                if line.startswith("CONFIG:"):
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        configs.append({"id": parts[1], "name": parts[2]})

        # Sort by name for consistent UI display
        configs.sort(key=lambda c: c["name"])
        self._openvas_configs_cache = configs
        return configs

    async def get_openvas_families(self) -> list:
        """Query available OpenVAS NVT families from GVM via GMP."""
        if self._openvas_families_cache is not None:
            return self._openvas_families_cache

        password = await self._get_openvas_password()
        if not password:
            return []

        script = '''
import socket, os, sys
import xml.etree.ElementTree as ET

SOCK_PATH = "/run/gvmd/gvmd.sock"
PASSWORD = os.environ.get("GMP_PASSWORD", "")

def send_gmp(sock, xml_str):
    sock.sendall(xml_str.encode("utf-8"))
    response = b""
    while True:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk
            text = response.decode("utf-8", errors="replace")
            for tag in ["authenticate_response", "get_nvt_families_response"]:
                if f"</{tag}>" in text:
                    return text
        except socket.timeout:
            break
    return response.decode("utf-8", errors="replace")

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(SOCK_PATH)

    auth_xml = f\'<authenticate><credentials><username>admin</username><password>{PASSWORD}</password></credentials></authenticate>\'
    resp = send_gmp(sock, auth_xml)

    resp = send_gmp(sock, \'<get_nvt_families/>\')
    root = ET.fromstring(resp)
    for fam in root.findall(".//family"):
        name = fam.findtext("name", "")
        max_nvt = fam.findtext("max_nvt_count", "0")
        if name:
            print(f"FAMILY:{name}:{max_nvt}")

    sock.close()
except Exception as e:
    print(f"ERROR:{e}", file=sys.stderr)
    sys.exit(1)
'''

        result = await self.process_manager.run_command_simple(
            ["kubectl", "exec", "-n", "openvas", "deployment/greenbone", "-c", "gvmd",
             "--", "env", f"GMP_PASSWORD={password}",
             "python3", "-c", script],
            timeout=60
        )

        families = []
        if result.success and result.output:
            for line in result.output.strip().split("\n"):
                if line.startswith("FAMILY:"):
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        families.append({
                            "name": parts[1],
                            "nvt_count": int(parts[2]) if parts[2].isdigit() else 0
                        })

        # Sort by name for consistent UI display
        families.sort(key=lambda f: f["name"])
        self._openvas_families_cache = families
        return families

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
            custom_modules=request.custom_modules,
            openvas_config=request.openvas_config,
            openvas_families=request.openvas_families,
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
                            uploaded = await self._upload_to_faraday(
                                xml_result, tool.value, faraday_creds,
                                scan_id=scan.id, scan_profile=profile.value
                            )
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
        openvas_config = self.current_scan.openvas_config
        openvas_families = self.current_scan.openvas_families

        # Determine config_id based on custom settings or profile
        if profile == ScanProfile.CUSTOM and openvas_config:
            # User selected a specific preset config
            config_id = openvas_config
            use_custom_families = False
        elif profile == ScanProfile.CUSTOM and openvas_families:
            # User selected specific NVT families — will create a custom config
            config_id = None
            use_custom_families = True
        else:
            # Standard profile-based config
            config_id = OPENVAS_SCAN_CONFIGS.get(profile, OPENVAS_SCAN_CONFIGS[ScanProfile.STANDARD])
            use_custom_families = False

        await self.log("openvas", "info", "Connecting to OpenVAS GVM daemon...")

        # Get OpenVAS admin password from k8s secret
        openvas_password = await self._get_openvas_password()
        if not openvas_password:
            await self.log("openvas", "error", "Could not retrieve OpenVAS credentials from cluster")
            return None

        # Python GMP script that runs inside the gvmd container
        # Uses stdlib only: socket + xml.etree.ElementTree
        if use_custom_families:
            gmp_script = self._build_gmp_custom_families_script(scan_id, target, openvas_families, profile)
        else:
            gmp_script = self._build_gmp_script(scan_id, target, config_id, profile)

        if use_custom_families:
            await self.log("openvas", "info", f"Creating custom config with {len(openvas_families)} NVT families for {target}...")
        elif profile == ScanProfile.CUSTOM and openvas_config:
            await self.log("openvas", "info", f"Using selected config for {target}...")
        else:
            await self.log("openvas", "info", f"Creating scan target and task for {target}...")

        # Execute the GMP script inside the gvmd container
        openvas_timeout = OPENVAS_TIMEOUTS.get(profile, OPENVAS_TIMEOUTS[ScanProfile.STANDARD])
        result = await self.process_manager.run_command(
            ["kubectl", "exec", "-n", "openvas", "deployment/greenbone", "-c", "gvmd",
             "--", "env", f"GMP_PASSWORD={openvas_password}",
             "python3", "-u", "-c", gmp_script],
            on_output=lambda line: self._log_openvas_line(line),
            timeout=openvas_timeout
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

        output_len = len(output)
        await self.log("openvas", "warn", f"Could not extract XML report from OpenVAS output ({output_len} bytes)")
        # Log last 30 lines for debugging (like Nmap handler)
        for line in output.split("\n")[-30:]:
            line = line.strip()
            if line and not line.startswith("<"):
                await self.log("openvas", "info", f"  {line}")
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

    def _build_gmp_script(self, scan_id: str, target: str, config_id: str,
                          profile: ScanProfile = ScanProfile.STANDARD) -> str:
        """Build a self-contained Python GMP script for OpenVAS scanning."""
        # Map profile to preferred port list key
        # Quick: all TCP + top 100 UDP (skips full UDP scan)
        # Standard: all TCP only (skip slow UDP scan entirely)
        # Thorough/Custom: all TCP + all UDP (comprehensive)
        port_list_pref = {
            ScanProfile.QUICK: "all_tcp_nmap_top100_udp",
            ScanProfile.STANDARD: "all_tcp",
            ScanProfile.THOROUGH: "all_tcp_udp",
            ScanProfile.CUSTOM: "all_tcp_udp",
        }.get(profile, "all_tcp")

        return f'''
import socket, os, sys, time
import xml.etree.ElementTree as ET

SOCK_PATH = "/run/gvmd/gvmd.sock"
PASSWORD = os.environ.get("GMP_PASSWORD", "")
TARGET = "{target}"
CONFIG_ID = "{config_id}"
SCAN_ID = "{scan_id}"
REPORT_FORMAT = "{OPENVAS_XML_FORMAT}"
# Profile-based port list preference
PREFERRED_PORT_LIST = "{port_list_pref}"
# Well-known port list UUIDs
PORT_LISTS = {{
    "all_tcp_udp": "4a4717fe-57d2-11e1-9a26-406186ea4fc5",
    "all_tcp": "33d0cd82-57c6-11e1-8ed1-406186ea4fc5",
    "all_tcp_nmap_top100_udp": "730ef368-57e2-11e1-a90f-406186ea4fc5",
}}

def send_gmp(sock, xml_str, end_tag=None):
    """Send a GMP command and receive the response."""
    sock.sendall(xml_str.encode("utf-8"))
    response = b""
    # Determine which end tag to look for
    if end_tag:
        search_tags = [end_tag]
    else:
        search_tags = ["authenticate_response", "create_target_response",
                    "create_task_response", "start_task_response",
                    "get_tasks_response", "get_reports_response",
                    "delete_target_response", "delete_task_response",
                    "get_port_lists_response"]
    while True:
        try:
            chunk = sock.recv(131072)
            if not chunk:
                break
            response += chunk
            # Only check the tail of the response for the end tag (avoids O(n^2))
            tail = response[-256:].decode("utf-8", errors="replace")
            for tag in search_tags:
                if f"</{{tag}}>" in tail:
                    return response.decode("utf-8", errors="replace")
        except socket.timeout:
            break
    return response.decode("utf-8", errors="replace")

def get_status_info(xml_text):
    """Get the status code and status_text from a GMP response."""
    try:
        root = ET.fromstring(xml_text)
        return root.attrib.get("status", ""), root.attrib.get("status_text", "")
    except ET.ParseError:
        return "", ""

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(SOCK_PATH)
    print("STATUS: Connected to GVM daemon", flush=True)

    # Authenticate
    auth_xml = f'<authenticate><credentials><username>admin</username><password>{{PASSWORD}}</password></credentials></authenticate>'
    resp = send_gmp(sock, auth_xml)
    status, status_text = get_status_info(resp)
    if status != "200":
        print(f"SCAN:FAILED:Authentication failed: {{status_text}}", flush=True)
        sys.exit(1)
    print("STATUS: Authenticated with GVM", flush=True)

    # Find a valid port list — use profile-based preference, verify against GVM
    preferred_id = PORT_LISTS.get(PREFERRED_PORT_LIST, "")
    port_list_id = preferred_id
    resp = send_gmp(sock, '<get_port_lists/>')
    try:
        root = ET.fromstring(resp)
        available_pls = {{}}
        for pl in root.findall("port_list"):
            available_pls[pl.attrib.get("id", "")] = pl.findtext("name", "")
        if preferred_id and preferred_id in available_pls:
            port_list_id = preferred_id
            print(f"STATUS: Using port list {{available_pls[port_list_id]}} (profile: {{PREFERRED_PORT_LIST}})", flush=True)
        else:
            # Fallback: try all_tcp, then first available
            fallback = PORT_LISTS.get("all_tcp", "")
            if fallback in available_pls:
                port_list_id = fallback
            elif available_pls:
                port_list_id = next(iter(available_pls))
            print(f"STATUS: Preferred port list unavailable, using {{available_pls.get(port_list_id, port_list_id)}}", flush=True)
    except ET.ParseError:
        print(f"STATUS: Using default port list {{port_list_id}}", flush=True)

    # Create target (with port_list_id — required by GVM 22+)
    target_name = f"scan-{{SCAN_ID}}-target"
    create_target = f'<create_target><name>{{target_name}}</name><hosts>{{TARGET}}</hosts><port_list id="{{port_list_id}}"/></create_target>'
    resp = send_gmp(sock, create_target)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create target failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        target_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse target ID", flush=True)
        sys.exit(1)
    print(f"STATUS: Created target {{target_id}}", flush=True)

    # Create task
    task_name = f"scan-{{SCAN_ID}}-task"
    create_task = f'<create_task><name>{{task_name}}</name><target id="{{target_id}}"/><config id="{{CONFIG_ID}}"/></create_task>'
    resp = send_gmp(sock, create_task)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create task failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        task_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse task ID", flush=True)
        sys.exit(1)
    print(f"STATUS: Created task {{task_id}}", flush=True)

    # Start task
    start = f'<start_task task_id="{{task_id}}"/>'
    resp = send_gmp(sock, start)
    status, status_text = get_status_info(resp)
    if status not in ("200", "202"):
        print(f"SCAN:FAILED:Start task failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    # Extract report ID from start response
    try:
        root = ET.fromstring(resp)
        report_elem = root.find(".//report_id")
        report_id = report_elem.text if report_elem is not None else ""
    except:
        report_id = ""
    print(f"STATUS: Scan started (report {{report_id}})", flush=True)

    # Poll for completion — progress-aware timeout
    # Stale limit: if no progress change for 30 minutes, bail out
    # No fixed max — the outer asyncio timeout (profile-dependent) is the hard ceiling
    stale_limit = 180  # 180 x 10s = 30 min with no progress change
    stale_count = 0
    last_result_count = 0
    last_progress_val = -1
    poll_count = 0
    scan_done = False
    while True:
        time.sleep(10)
        poll_count += 1
        get_task = f'<get_tasks task_id="{{task_id}}"/>'
        resp = send_gmp(sock, get_task)
        try:
            root = ET.fromstring(resp)
            task_elem = root.find(".//task")
            if task_elem is not None:
                task_status = task_elem.findtext("status", "")
                progress_elem = task_elem.find("progress")
                progress = progress_elem.text if progress_elem is not None else "0"
                progress_int = int(progress) if progress.isdigit() else 0
                # Extract intermediate result count
                result_count = 0
                current_report = task_elem.find(".//current_report")
                if current_report is not None:
                    rc = current_report.findtext(".//result_count/full", "0")
                    result_count = int(rc) if rc.isdigit() else 0
                # Extract per-host progress (format: "host_ip:percentage")
                host_progress_elems = task_elem.findall(".//progress/host_progress")
                active_hosts = 0
                host_pcts = []
                for hp in host_progress_elems:
                    host_text = (hp.text or "").strip()
                    if ":" in host_text:
                        parts = host_text.rsplit(":", 1)
                        try:
                            pct = int(parts[1])
                            if pct >= 0:
                                host_pcts.append(pct)
                                if 0 < pct < 100:
                                    active_hosts += 1
                        except (ValueError, IndexError):
                            pass
                avg_host_pct = sum(host_pcts) // len(host_pcts) if host_pcts else 0
                # Build detailed progress line
                elapsed = poll_count * 10
                elapsed_str = f"{{elapsed // 3600}}h {{(elapsed % 3600) // 60}}m {{elapsed % 60}}s"
                detail = f"{{task_status}} ({{progress}}% overall"
                if host_pcts:
                    detail += f", {{avg_host_pct}}% avg host, {{active_hosts}} active"
                detail += f") | {{result_count}} results | elapsed {{elapsed_str}}"
                stale_remaining = (stale_limit - stale_count) * 10 // 60
                detail += f" | stale timeout in {{stale_remaining}}m"
                print(f"PROGRESS: {{detail}}", flush=True)
                # Check for progress change — reset stale counter if anything moved
                if result_count != last_result_count or progress_int != last_progress_val:
                    stale_count = 0
                    last_result_count = result_count
                    last_progress_val = progress_int
                else:
                    stale_count += 1
                if task_status == "Done":
                    # Get the report ID from the task
                    if not report_id:
                        report_elem = task_elem.find(".//report")
                        report_id = report_elem.attrib.get("id", "") if report_elem is not None else ""
                    scan_done = True
                    break
                elif task_status in ("Stop Requested", "Stopped", "Error"):
                    # If scan was nearly done, try to retrieve partial results
                    if progress_int >= 80 and task_status == "Stopped":
                        print(f"STATUS: Scan stopped at {{progress_int}}% — attempting to retrieve partial results", flush=True)
                        if not report_id:
                            report_elem = task_elem.find(".//report")
                            report_id = report_elem.attrib.get("id", "") if report_elem is not None else ""
                        scan_done = True
                        break
                    print(f"SCAN:FAILED:Task ended with status {{task_status}}", flush=True)
                    sys.exit(1)
                # Stale timeout — no progress for 30 minutes
                if stale_count >= stale_limit:
                    elapsed_total = poll_count * 10
                    print(f"SCAN:FAILED:Scan stalled — no progress change for 30 minutes (elapsed {{elapsed_total // 3600}}h {{(elapsed_total % 3600) // 60}}m)", flush=True)
                    sys.exit(1)
        except ET.ParseError:
            pass
    if not scan_done:
        print("SCAN:FAILED:Polling loop exited unexpectedly", flush=True)
        sys.exit(1)

    # Get report in XML format
    if report_id:
        print("STATUS: Retrieving scan report...", flush=True)
        get_report = f'<get_reports report_id="{{report_id}}" format_id="{{REPORT_FORMAT}}" details="1"/>'
        # Large reports need generous timeout (300s per chunk wait)
        sock.settimeout(300)
        resp = send_gmp(sock, get_report, end_tag="get_reports_response")
        resp_len = len(resp)
        print(f"STATUS: Report response received ({{resp_len}} bytes)", flush=True)
        if resp_len == 0:
            print("SCAN:FAILED:Empty response when retrieving report", flush=True)
            sys.exit(1)
        print("REPORT_XML_START", flush=True)
        # Extract the report XML from the GMP response
        try:
            root = ET.fromstring(resp)
            report_elem = root.find(".//report")
            if report_elem is not None:
                print(ET.tostring(report_elem, encoding="unicode"), flush=True)
            else:
                print(f"ERROR: No <report> element found in response ({{resp_len}} bytes)", flush=True)
                # Print first 500 chars for debugging
                print(resp[:500], flush=True)
        except ET.ParseError as parse_err:
            print(f"ERROR: XML parse failed: {{parse_err}}", flush=True)
            # Check if we got a partial response
            if "</get_reports_response>" not in resp:
                print(f"ERROR: Response appears truncated ({{resp_len}} bytes, no closing tag)", flush=True)
            # Still output what we have - extraction code will try to use it
            print(resp, flush=True)
        print("REPORT_XML_END", flush=True)
    else:
        print("SCAN:FAILED:No report ID available", flush=True)

    # Cleanup: delete task and target
    try:
        send_gmp(sock, f'<delete_task task_id="{{task_id}}" ultimate="1"/>')
        send_gmp(sock, f'<delete_target target_id="{{target_id}}" ultimate="1"/>')
    except:
        pass

    sock.close()
    print("STATUS: OpenVAS scan complete", flush=True)

except Exception as e:
    print(f"SCAN:FAILED:{{e}}", flush=True)
    sys.exit(1)
'''

    def _build_gmp_custom_families_script(self, scan_id: str, target: str,
                                            families: List[str],
                                            profile: ScanProfile = ScanProfile.STANDARD) -> str:
        """Build a GMP script that creates a custom config with selected NVT families."""
        # Build the family XML for modify_config
        family_xml_parts = []
        for fam in families:
            family_xml_parts.append(
                f'<family><name>{fam}</name><all>1</all><growing>1</growing></family>'
            )
        families_xml = "".join(family_xml_parts)

        # Map profile to preferred port list key (same logic as standard script)
        # Custom families are typically used with Standard+ profiles
        port_list_pref = {
            ScanProfile.QUICK: "all_tcp_nmap_top100_udp",
            ScanProfile.STANDARD: "all_tcp",
            ScanProfile.THOROUGH: "all_tcp_udp",
            ScanProfile.CUSTOM: "all_tcp_udp",
        }.get(profile, "all_tcp")

        return f'''
import socket, os, sys, time
import xml.etree.ElementTree as ET

SOCK_PATH = "/run/gvmd/gvmd.sock"
PASSWORD = os.environ.get("GMP_PASSWORD", "")
TARGET = "{target}"
SCAN_ID = "{scan_id}"
REPORT_FORMAT = "{OPENVAS_XML_FORMAT}"
# Base config: Full and Fast (we clone it, then replace families)
BASE_CONFIG_ID = "daba56c8-73ec-11df-a475-002264764cea"
# Profile-based port list preference
PREFERRED_PORT_LIST = "{port_list_pref}"
PORT_LISTS = {{
    "all_tcp_udp": "4a4717fe-57d2-11e1-9a26-406186ea4fc5",
    "all_tcp": "33d0cd82-57c6-11e1-8ed1-406186ea4fc5",
    "all_tcp_nmap_top100_udp": "730ef368-57e2-11e1-a90f-406186ea4fc5",
}}

def send_gmp(sock, xml_str, end_tag=None):
    """Send a GMP command and receive the response."""
    sock.sendall(xml_str.encode("utf-8"))
    response = b""
    if end_tag:
        search_tags = [end_tag]
    else:
        search_tags = ["authenticate_response", "create_target_response",
                    "create_config_response", "modify_config_response",
                    "create_task_response", "start_task_response",
                    "get_tasks_response", "get_reports_response",
                    "delete_target_response", "delete_task_response",
                    "delete_config_response", "get_port_lists_response"]
    while True:
        try:
            chunk = sock.recv(131072)
            if not chunk:
                break
            response += chunk
            # Only check the tail of the response for the end tag (avoids O(n^2))
            tail = response[-256:].decode("utf-8", errors="replace")
            for tag in search_tags:
                if f"</{{tag}}>" in tail:
                    return response.decode("utf-8", errors="replace")
        except socket.timeout:
            break
    return response.decode("utf-8", errors="replace")

def get_status_info(xml_text):
    try:
        root = ET.fromstring(xml_text)
        return root.attrib.get("status", ""), root.attrib.get("status_text", "")
    except ET.ParseError:
        return "", ""

custom_config_id = None

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(SOCK_PATH)
    print("STATUS: Connected to GVM daemon", flush=True)

    # Authenticate
    auth_xml = f\'<authenticate><credentials><username>admin</username><password>{{PASSWORD}}</password></credentials></authenticate>\'
    resp = send_gmp(sock, auth_xml)
    status, status_text = get_status_info(resp)
    if status != "200":
        print(f"SCAN:FAILED:Authentication failed: {{status_text}}", flush=True)
        sys.exit(1)
    print("STATUS: Authenticated with GVM", flush=True)

    # Find a valid port list — use profile-based preference, verify against GVM
    preferred_id = PORT_LISTS.get(PREFERRED_PORT_LIST, PORT_LISTS["all_tcp"])
    port_list_id = preferred_id
    resp = send_gmp(sock, '<get_port_lists/>')
    try:
        root = ET.fromstring(resp)
        available_pls = {{pl.attrib.get("id", ""): pl.findtext("name", "") for pl in root.findall("port_list")}}
        if preferred_id in available_pls:
            port_list_id = preferred_id
            print(f"STATUS: Using port list {{available_pls[port_list_id]}} (profile: {{PREFERRED_PORT_LIST}})", flush=True)
        else:
            fallback = PORT_LISTS.get("all_tcp", "")
            if fallback in available_pls:
                port_list_id = fallback
            elif available_pls:
                port_list_id = next(iter(available_pls))
            print(f"STATUS: Preferred port list unavailable, using {{available_pls.get(port_list_id, port_list_id)}}", flush=True)
    except ET.ParseError:
        pass

    # Create custom config by cloning base
    config_name = f"scan-{{SCAN_ID}}-custom-config"
    create_cfg = f\'<create_config><copy>{{BASE_CONFIG_ID}}</copy><name>{{config_name}}</name></create_config>\'
    resp = send_gmp(sock, create_cfg)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create config failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        custom_config_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse config ID", flush=True)
        sys.exit(1)
    print(f"STATUS: Created custom config {{custom_config_id}}", flush=True)

    # Modify config to set selected NVT families
    modify_xml = f\'<modify_config config_id="{{custom_config_id}}"><nvt_family_selection>{families_xml}</nvt_family_selection></modify_config>\'
    resp = send_gmp(sock, modify_xml)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"STATUS: Warning - modify config returned status {{status}}: {{status_text}}", flush=True)
    else:
        print("STATUS: Configured NVT families on custom config", flush=True)

    # Create target (with port_list_id — required by GVM 22+)
    target_name = f"scan-{{SCAN_ID}}-target"
    create_target = f\'<create_target><name>{{target_name}}</name><hosts>{{TARGET}}</hosts><port_list id="{{port_list_id}}"/></create_target>\'
    resp = send_gmp(sock, create_target)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create target failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        target_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse target ID", flush=True)
        sys.exit(1)
    print(f"STATUS: Created target {{target_id}}", flush=True)

    # Create task with custom config
    task_name = f"scan-{{SCAN_ID}}-task"
    create_task = f\'<create_task><name>{{task_name}}</name><target id="{{target_id}}"/><config id="{{custom_config_id}}"/></create_task>\'
    resp = send_gmp(sock, create_task)
    status, status_text = get_status_info(resp)
    if status not in ("200", "201"):
        print(f"SCAN:FAILED:Create task failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        task_id = root.attrib.get("id", "")
    except:
        print("SCAN:FAILED:Could not parse task ID", flush=True)
        sys.exit(1)
    print(f"STATUS: Created task {{task_id}}", flush=True)

    # Start task
    start = f\'<start_task task_id="{{task_id}}"/>\'
    resp = send_gmp(sock, start)
    status, status_text = get_status_info(resp)
    if status not in ("200", "202"):
        print(f"SCAN:FAILED:Start task failed (status {{status}}): {{status_text}}", flush=True)
        sys.exit(1)
    try:
        root = ET.fromstring(resp)
        report_elem = root.find(".//report_id")
        report_id = report_elem.text if report_elem is not None else ""
    except:
        report_id = ""
    print(f"STATUS: Scan started (report {{report_id}})", flush=True)

    # Poll for completion — progress-aware timeout
    # Stale limit: if no progress change for 30 minutes, bail out
    # No fixed max — the outer asyncio timeout (profile-dependent) is the hard ceiling
    stale_limit = 180  # 180 x 10s = 30 min with no progress change
    stale_count = 0
    last_result_count = 0
    last_progress_val = -1
    poll_count = 0
    scan_done = False
    while True:
        time.sleep(10)
        poll_count += 1
        get_task = f\'<get_tasks task_id="{{task_id}}"/>\'
        resp = send_gmp(sock, get_task)
        try:
            root = ET.fromstring(resp)
            task_elem = root.find(".//task")
            if task_elem is not None:
                task_status = task_elem.findtext("status", "")
                progress_elem = task_elem.find("progress")
                progress = progress_elem.text if progress_elem is not None else "0"
                progress_int = int(progress) if progress.isdigit() else 0
                # Extract intermediate result count
                result_count = 0
                current_report = task_elem.find(".//current_report")
                if current_report is not None:
                    rc = current_report.findtext(".//result_count/full", "0")
                    result_count = int(rc) if rc.isdigit() else 0
                # Extract per-host progress (format: "host_ip:percentage")
                host_progress_elems = task_elem.findall(".//progress/host_progress")
                active_hosts = 0
                host_pcts = []
                for hp in host_progress_elems:
                    host_text = (hp.text or "").strip()
                    if ":" in host_text:
                        parts = host_text.rsplit(":", 1)
                        try:
                            pct = int(parts[1])
                            if pct >= 0:
                                host_pcts.append(pct)
                                if 0 < pct < 100:
                                    active_hosts += 1
                        except (ValueError, IndexError):
                            pass
                avg_host_pct = sum(host_pcts) // len(host_pcts) if host_pcts else 0
                # Build detailed progress line
                elapsed = poll_count * 10
                elapsed_str = f"{{elapsed // 3600}}h {{(elapsed % 3600) // 60}}m {{elapsed % 60}}s"
                detail = f"{{task_status}} ({{progress}}% overall"
                if host_pcts:
                    detail += f", {{avg_host_pct}}% avg host, {{active_hosts}} active"
                detail += f") | {{result_count}} results | elapsed {{elapsed_str}}"
                stale_remaining = (stale_limit - stale_count) * 10 // 60
                detail += f" | stale timeout in {{stale_remaining}}m"
                print(f"PROGRESS: {{detail}}", flush=True)
                # Check for progress change — reset stale counter if anything moved
                if result_count != last_result_count or progress_int != last_progress_val:
                    stale_count = 0
                    last_result_count = result_count
                    last_progress_val = progress_int
                else:
                    stale_count += 1
                if task_status == "Done":
                    if not report_id:
                        report_elem = task_elem.find(".//report")
                        report_id = report_elem.attrib.get("id", "") if report_elem is not None else ""
                    scan_done = True
                    break
                elif task_status in ("Stop Requested", "Stopped", "Error"):
                    # If scan was nearly done, try to retrieve partial results
                    if progress_int >= 80 and task_status == "Stopped":
                        print(f"STATUS: Scan stopped at {{progress_int}}% — attempting to retrieve partial results", flush=True)
                        if not report_id:
                            report_elem = task_elem.find(".//report")
                            report_id = report_elem.attrib.get("id", "") if report_elem is not None else ""
                        scan_done = True
                        break
                    print(f"SCAN:FAILED:Task ended with status {{task_status}}", flush=True)
                    sys.exit(1)
                # Stale timeout — no progress for 30 minutes
                if stale_count >= stale_limit:
                    elapsed_total = poll_count * 10
                    print(f"SCAN:FAILED:Scan stalled — no progress change for 30 minutes (elapsed {{elapsed_total // 3600}}h {{(elapsed_total % 3600) // 60}}m)", flush=True)
                    sys.exit(1)
        except ET.ParseError:
            pass
    if not scan_done:
        print("SCAN:FAILED:Polling loop exited unexpectedly", flush=True)
        sys.exit(1)

    # Get report in XML format
    if report_id:
        print("STATUS: Retrieving scan report...", flush=True)
        get_report = f\'<get_reports report_id="{{report_id}}" format_id="{{REPORT_FORMAT}}" details="1"/>\'
        sock.settimeout(300)
        resp = send_gmp(sock, get_report, end_tag="get_reports_response")
        resp_len = len(resp)
        print(f"STATUS: Report response received ({{resp_len}} bytes)", flush=True)
        if resp_len == 0:
            print("SCAN:FAILED:Empty response when retrieving report", flush=True)
            sys.exit(1)
        print("REPORT_XML_START", flush=True)
        try:
            root = ET.fromstring(resp)
            report_elem = root.find(".//report")
            if report_elem is not None:
                print(ET.tostring(report_elem, encoding="unicode"), flush=True)
            else:
                print(f"ERROR: No <report> element found in response ({{resp_len}} bytes)", flush=True)
                print(resp[:500], flush=True)
        except ET.ParseError as parse_err:
            print(f"ERROR: XML parse failed: {{parse_err}}", flush=True)
            if "</get_reports_response>" not in resp:
                print(f"ERROR: Response appears truncated ({{resp_len}} bytes, no closing tag)", flush=True)
            print(resp, flush=True)
        print("REPORT_XML_END", flush=True)
    else:
        print("SCAN:FAILED:No report ID available", flush=True)

    # Cleanup: delete task, target, and custom config
    try:
        send_gmp(sock, f\'<delete_task task_id="{{task_id}}" ultimate="1"/>\')
        send_gmp(sock, f\'<delete_target target_id="{{target_id}}" ultimate="1"/>\')
        if custom_config_id:
            send_gmp(sock, f\'<delete_config config_id="{{custom_config_id}}" ultimate="1"/>\')
            print("STATUS: Cleaned up custom config", flush=True)
    except:
        pass

    sock.close()
    print("STATUS: OpenVAS scan complete", flush=True)

except Exception as e:
    print(f"SCAN:FAILED:{{e}}", flush=True)
    # Try to clean up custom config on failure
    try:
        if custom_config_id:
            send_gmp(sock, f\'<delete_config config_id="{{custom_config_id}}" ultimate="1"/>\')
    except:
        pass
    sys.exit(1)
'''

    # =========================================================================
    # METASPLOIT
    # =========================================================================

    def _build_msf_resource_script(self, target: str, profile: ScanProfile,
                                     scan_id: str, xml_path: str,
                                     custom_modules: list = None) -> str:
        """Build a Metasploit resource script based on scan profile.

        Quick:    db_nmap discovery only (fast port scan, no vuln modules)
        Standard: db_nmap service detection + common vulnerability scanners
        Thorough: db_nmap full scan + comprehensive auxiliary scanner suite
        Custom:   db_nmap + user-selected modules from catalog
        """
        lines = []

        # Phase 1: Network discovery via db_nmap
        nmap_flags = {
            ScanProfile.QUICK: "-T4 --top-ports 100",
            ScanProfile.STANDARD: "-T4 -sV --top-ports 1000",
            ScanProfile.THOROUGH: "-T4 -sV -sC --top-ports 1000",
            ScanProfile.CUSTOM: "-T4 -sV --top-ports 1000",
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

        # Select modules from catalog based on profile
        if profile == ScanProfile.CUSTOM:
            selected_ids = set(custom_modules or [])
            modules = [m for m in MSF_MODULE_CATALOG if m["id"] in selected_ids]
        elif profile == ScanProfile.QUICK:
            modules = []
        else:
            # standard or thorough — filter by profile name
            modules = [m for m in MSF_MODULE_CATALOG if profile.value in m["profiles"]]

        for mod in modules:
            add_module(mod["id"], mod.get("extra_opts"))

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
        custom_modules = self.current_scan.custom_modules

        # Select timeout based on profile
        if profile == ScanProfile.CUSTOM:
            module_count_est = len(custom_modules) if custom_modules else 0
            # Base 15 min for db_nmap + ~3 min per module
            msf_timeout = 900 + (module_count_est * 180)
        else:
            msf_timeout = {
                ScanProfile.QUICK: METASPLOIT_TIMEOUT_QUICK,
                ScanProfile.STANDARD: METASPLOIT_TIMEOUT_STANDARD,
                ScanProfile.THOROUGH: METASPLOIT_TIMEOUT_THOROUGH,
            }.get(profile, METASPLOIT_TIMEOUT_STANDARD)

        # Build the resource script
        rc_content = self._build_msf_resource_script(
            target, profile, scan_id, xml_path, custom_modules=custom_modules
        )

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
            ScanProfile.CUSTOM: "-T4 -sV --top-ports 1000",
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

    async def _upload_to_faraday(self, xml_content: str, tool_name: str, creds: dict,
                                scan_id: str = "", scan_profile: str = "") -> bool:
        """Upload scan results to Faraday via individual REST API calls.

        Uses faraday-plugins to parse XML, then creates hosts/services/vulns
        one by one via the synchronous REST API (avoids bulk_create which
        requires a Celery worker that isn't running in our deployment).

        Enhanced fields passed to Faraday:
        - tags: tool source + scan profile for filtering
        - data: raw evidence/proof from scan output
        - external_id: CVE identifiers for cross-referencing
        - policyviolations: compliance findings
        - VulnWeb type: for HTTP-related findings (path, method, website, etc.)
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
            # 4. Creates hosts/services/vulns with full context via REST API
            upload_script = (
                "import urllib.request, json, http.cookiejar, os, sys\n"
                "BASE = 'http://127.0.0.1:5985'\n"
                "WS = 'pentest'\n"
                f"TOOL = '{tool_name}'\n"
                f"SCAN_ID = '{scan_id}'\n"
                f"SCAN_PROFILE = '{scan_profile}'\n"
                "TOOL_TAGS = [f'tool:{TOOL}', f'profile:{SCAN_PROFILE}', f'scan:{SCAN_ID}']\n"
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
                "def api_put(path, body):\n"
                "    data = json.dumps(body).encode()\n"
                "    req = urllib.request.Request(BASE + path, method='PUT',\n"
                "        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, data=data)\n"
                "    resp = opener.open(req)\n"
                "    return json.loads(resp.read().decode())\n"
                "\n"
                "def api_get(path):\n"
                "    req = urllib.request.Request(BASE + path, headers={'X-CSRFToken': csrf})\n"
                "    resp = opener.open(req)\n"
                "    return json.loads(resp.read().decode())\n"
                "\n"
                "VALID_SEVERITIES = {'critical', 'high', 'medium', 'low', 'info', 'unclassified'}\n"
                "def normalize_severity(sev):\n"
                "    s = (sev or 'unclassified').lower().strip()\n"
                "    if s in VALID_SEVERITIES: return s\n"
                "    if s in ('information', 'informational', 'log'): return 'info'\n"
                "    if s in ('warning', 'moderate'): return 'medium'\n"
                "    if s in ('error', 'important', 'urgent'): return 'high'\n"
                "    return 'unclassified'\n"
                "\n"
                "def extract_cves(refs):\n"
                "    cves = []\n"
                "    for r in (refs or []):\n"
                "        r_str = str(r).upper()\n"
                "        if 'CVE-' in r_str:\n"
                "            import re\n"
                "            found = re.findall(r'CVE-\\d{4}-\\d{4,}', r_str)\n"
                "            cves.extend(found)\n"
                "    return list(set(cves))\n"
                "\n"
                "def is_web_vuln(vuln):\n"
                "    web_fields = ['path', 'website', 'method', 'request', 'response', 'query']\n"
                "    return any(vuln.get(f) for f in web_fields)\n"
                "\n"
                "def build_vuln_body(vuln, parent_id, parent_type):\n"
                "    severity = normalize_severity(vuln.get('severity', 'info'))\n"
                "    refs = vuln.get('refs', [])\n"
                "    cves = extract_cves(refs)\n"
                "    tags = list(TOOL_TAGS)\n"
                "    tags.append(f'severity:{severity}')\n"
                "    for cve in cves:\n"
                "        tags.append(f'cve:{cve}')\n"
                "    extra_tags = vuln.get('tags', [])\n"
                "    if extra_tags:\n"
                "        tags.extend([str(t) for t in extra_tags])\n"
                "    body = {\n"
                "        'name': vuln.get('name', 'Unknown'),\n"
                "        'desc': vuln.get('desc', ''),\n"
                "        'severity': severity,\n"
                "        'refs': refs,\n"
                "        'resolution': vuln.get('resolution', ''),\n"
                "        'data': vuln.get('data', ''),\n"
                "        'external_id': cves[0] if cves else vuln.get('external_id', ''),\n"
                "        'tags': tags,\n"
                "        'policyviolations': vuln.get('policyviolations', []),\n"
                "        'parent': parent_id,\n"
                "        'parent_type': parent_type,\n"
                "    }\n"
                "    if is_web_vuln(vuln):\n"
                "        body['type'] = 'VulnerabilityWeb'\n"
                "        for f in ['path', 'website', 'method', 'request', 'response',\n"
                "                  'query', 'params', 'pname', 'category']:\n"
                "            val = vuln.get(f, '')\n"
                "            if val:\n"
                "                body[f] = val\n"
                "    else:\n"
                "        body['type'] = 'Vulnerability'\n"
                "    return body\n"
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
                "            api_post('/_api/v3/ws', {'name': WS, 'description': 'CleanRoom automated security scans'})\n"
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
                "# Create hosts, services, and vulns with full context\n"
                "created_hosts = 0\n"
                "created_services = 0\n"
                "created_vulns = 0\n"
                "created_vulnwebs = 0\n"
                "errors = 0\n"
                "\n"
                "for h in hosts:\n"
                "    # Create host with tags\n"
                "    host_body = {\n"
                "        'ip': h.get('ip', ''),\n"
                "        'os': h.get('os', ''),\n"
                "        'hostnames': h.get('hostnames', []),\n"
                "        'description': h.get('description', ''),\n"
                "        'mac': h.get('mac', ''),\n"
                "        'tags': list(TOOL_TAGS),\n"
                "    }\n"
                "    try:\n"
                "        host_resp = api_post(f'/_api/v3/ws/{WS}/hosts', host_body)\n"
                "        host_id = host_resp.get('id')\n"
                "        created_hosts += 1\n"
                "    except urllib.error.HTTPError as e:\n"
                "        body = e.read().decode()\n"
                "        if e.code == 409:\n"
                "            try:\n"
                "                existing = json.loads(body)\n"
                "                host_id = existing.get('object', {}).get('id')\n"
                "                if host_id:\n"
                "                    created_hosts += 1\n"
                "                    # Update existing host tags to include this tool\n"
                "                    try:\n"
                "                        host_data = api_get(f'/_api/v3/ws/{WS}/hosts/{host_id}')\n"
                "                        existing_tags = host_data.get('tags', [])\n"
                "                        merged = list(set(existing_tags + TOOL_TAGS))\n"
                "                        api_put(f'/_api/v3/ws/{WS}/hosts/{host_id}', {'tags': merged})\n"
                "                    except:\n"
                "                        pass\n"
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
                "    # Create services with tags and summary\n"
                "    svc_id_map = {}\n"
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
                "        # Build summary from version info\n"
                "        ver = svc.get('version', '')\n"
                "        svc_name = svc.get('name', '')\n"
                "        if ver and svc_name:\n"
                "            svc_body['summary'] = f'{svc_name} {ver}'.strip()\n"
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
                "    # Create host-level vulnerabilities with full context\n"
                "    for vuln in h.get('vulnerabilities', []):\n"
                "        vuln_body = build_vuln_body(vuln, host_id, 'Host')\n"
                "        try:\n"
                "            api_post(f'/_api/v3/ws/{WS}/vulns', vuln_body)\n"
                "            if vuln_body.get('type') == 'VulnerabilityWeb':\n"
                "                created_vulnwebs += 1\n"
                "            else:\n"
                "                created_vulns += 1\n"
                "        except urllib.error.HTTPError:\n"
                "            errors += 1\n"
                "        except Exception:\n"
                "            errors += 1\n"
                "\n"
                "    # Create service-level vulnerabilities with full context\n"
                "    for svc in h.get('services', []):\n"
                "        svc_port = int(svc.get('port', 0) or 0)\n"
                "        svc_id = svc_id_map.get(svc_port)\n"
                "        if not svc_id:\n"
                "            continue\n"
                "        for vuln in svc.get('vulnerabilities', []):\n"
                "            vuln_body = build_vuln_body(vuln, svc_id, 'Service')\n"
                "            try:\n"
                "                api_post(f'/_api/v3/ws/{WS}/vulns', vuln_body)\n"
                "                if vuln_body.get('type') == 'VulnerabilityWeb':\n"
                "                    created_vulnwebs += 1\n"
                "                else:\n"
                "                    created_vulns += 1\n"
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
                "total = created_hosts + created_services + created_vulns + created_vulnwebs\n"
                "if total > 0:\n"
                "    parts = [f'{created_hosts} hosts', f'{created_services} services', f'{created_vulns} vulns']\n"
                "    if created_vulnwebs > 0:\n"
                "        parts.append(f'{created_vulnwebs} web vulns')\n"
                "    if errors > 0:\n"
                "        parts.append(f'{errors} errors')\n"
                "    print(f'UPLOAD:OK:' + ', '.join(parts))\n"
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
