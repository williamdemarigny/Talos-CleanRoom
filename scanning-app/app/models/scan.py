"""Scan state models for security scanning operations."""

import ipaddress
import re
from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator

from talos_common.models.common import BaseStatus, BaseLogEntry


class ScanStatus(str, Enum):
    """Status of a scan or scan tool."""
    IDLE = BaseStatus.IDLE.value
    RUNNING = BaseStatus.RUNNING.value
    COMPLETED = BaseStatus.COMPLETED.value
    FAILED = BaseStatus.FAILED.value
    ABORTED = BaseStatus.ABORTED.value


class ScanTool(str, Enum):
    """Available scanning tools."""
    NMAP = "nmap"
    OPENVAS = "openvas"
    METASPLOIT = "metasploit"
    WPSCAN = "wpscan"


class ScanProfile(str, Enum):
    """Scan intensity profiles."""
    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"
    CUSTOM = "custom"


class ScanToolState(BaseModel):
    """State of a single scan tool within a scan."""
    tool: ScanTool
    status: ScanStatus = ScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    findings_count: int = 0
    uploaded_to_faraday: bool = False


class ScanState(BaseModel):
    """Current state of a scan operation."""
    id: str
    target: str
    profile: ScanProfile = ScanProfile.STANDARD
    custom_modules: Optional[List[str]] = None
    openvas_config: Optional[str] = None
    openvas_families: Optional[List[str]] = None
    nmap_scripts: Optional[str] = None
    lab_env_id: Optional[str] = None
    tools: List[ScanToolState] = []
    status: ScanStatus = ScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    faraday_workspace: str = "pentest"


class ScanLogEntry(BaseLogEntry):
    """A log entry from a scan operation."""
    tool: Optional[str] = None


# RFC 1123 hostname pattern (labels: alphanumeric + hyphens, no leading/trailing hyphen)
_HOSTNAME_RE = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
)


def _validate_single_target(token: str) -> str:
    """Validate a single scan target token (IP, CIDR, hostname, or host:port).

    Accepts:
      - IPv4/IPv6 address (e.g. 192.168.1.1)
      - CIDR range (e.g. 10.0.0.0/24)
      - RFC 1123 hostname (e.g. server.example.com)
      - host:port (e.g. svc.ns.svc.cluster.local:8983)

    Raises ValueError if the token is not a valid target.
    """
    # Check for host:port format
    host_part = token
    port_part = None
    if token.startswith('['):
        # IPv6 bracket notation: [::1]:8080
        bracket_end = token.find(']')
        if bracket_end > 0 and bracket_end + 1 < len(token) and token[bracket_end + 1] == ':':
            host_part = token[1:bracket_end]
            port_part = token[bracket_end + 2:]
    elif ':' in token:
        # Could be host:port or plain IPv6
        last_colon = token.rfind(':')
        candidate_port = token[last_colon + 1:]
        candidate_host = token[:last_colon]
        if candidate_port.isdigit() and 1 <= int(candidate_port) <= 65535:
            # Check if the full token is a valid IPv6 address (not host:port)
            try:
                ipaddress.ip_address(token)
                return token
            except ValueError:
                host_part = candidate_host
                port_part = candidate_port

    # Validate port if present
    if port_part is not None:
        if not port_part.isdigit() or not (1 <= int(port_part) <= 65535):
            raise ValueError(
                f"Invalid port in target: {token!r}. Port must be 1-65535."
            )

    # Try IP address
    try:
        ipaddress.ip_address(host_part)
        return token
    except ValueError:
        pass
    # Try CIDR notation (only without port — CIDR with port is nonsensical)
    if port_part is None:
        try:
            ipaddress.ip_network(host_part, strict=False)
            return token
        except ValueError:
            pass
    # Try hostname (RFC 1123)
    if _HOSTNAME_RE.match(host_part) and len(host_part) <= 253:
        return token
    raise ValueError(
        f"Invalid target: {token!r}. Must be a valid IP address, "
        "CIDR range, hostname, or host:port."
    )


class ScanRequest(BaseModel):
    """Request to start a scan."""
    target: str
    tools: List[ScanTool]
    profile: ScanProfile = ScanProfile.STANDARD
    custom_modules: Optional[List[str]] = None
    openvas_config: Optional[str] = None
    openvas_families: Optional[List[str]] = None
    nmap_scripts: Optional[str] = None
    lab_env_id: Optional[str] = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Target must not be empty")
        # Support comma-separated list of targets
        tokens = [t.strip() for t in v.split(",") if t.strip()]
        if not tokens:
            raise ValueError("Target must not be empty")
        for token in tokens:
            _validate_single_target(token)
        return v
