"""IOC scan state models for LOKI-RS host-based IOC scanning."""

import ipaddress
import re
from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator

from talos_common.models.common import BaseStatus, BaseLogEntry


class MountType(str, Enum):
    """Filesystem mount protocol for remote scanning."""
    SSH = "ssh"
    SMB = "smb"


class IocScanStatus(str, Enum):
    """Status of an IOC scan operation."""
    IDLE = BaseStatus.IDLE.value
    MOUNTING = "mounting"
    SCANNING = "scanning"
    PARSING = "parsing"
    UPLOADING = "uploading"
    COMPLETED = BaseStatus.COMPLETED.value
    FAILED = BaseStatus.FAILED.value
    ABORTED = BaseStatus.ABORTED.value


class IocSeverity(str, Enum):
    """LOKI-RS finding severity levels."""
    NOTICE = "notice"
    WARNING = "warning"
    ALERT = "alert"


class IocFinding(BaseModel):
    """A single IOC finding from LOKI-RS."""
    severity: IocSeverity
    score: int
    file_path: str
    rule_name: Optional[str] = None
    description: str
    matched_strings: Optional[List[str]] = None
    hash_md5: Optional[str] = None
    hash_sha256: Optional[str] = None
    tags: List[str] = []


class IocScanLogEntry(BaseLogEntry):
    """A log entry from an IOC scan operation."""
    pass


# RFC 1123 hostname pattern
_HOSTNAME_RE = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
)
# Scan path: absolute path only, no shell metacharacters or traversal
_SCAN_PATH_PATTERN = re.compile(r'^/[a-zA-Z0-9/.\-_]*$')


class IocScanRequest(BaseModel):
    """Request to start an IOC scan."""
    target: str
    mount_type: MountType
    scan_path: str = "/"

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Target must not be empty")
        # IOC scan targets a single host (IP or hostname)
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if _HOSTNAME_RE.match(v) and len(v) <= 253:
            return v
        raise ValueError(
            f"Invalid target: {v!r}. Must be a valid IP address or hostname."
        )

    @field_validator("scan_path")
    @classmethod
    def validate_scan_path(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("Scan path must not contain '..' (path traversal)")
        if not v.startswith("/"):
            raise ValueError("Scan path must be an absolute path starting with '/'")
        if not _SCAN_PATH_PATTERN.match(v):
            raise ValueError(
                "Scan path contains invalid characters. "
                "Only alphanumerics, slashes, dots, hyphens, and underscores are allowed."
            )
        return v
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_key: Optional[str] = None
    smb_share: Optional[str] = None
    smb_username: Optional[str] = None
    smb_password: Optional[str] = None
    smb_domain: Optional[str] = None
    max_file_size_mb: int = 64
    scan_archives: bool = True


class IocScanState(BaseModel):
    """Current state of an IOC scan operation."""
    id: str
    target: str
    mount_type: MountType
    scan_path: str
    status: IocScanStatus = IocScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    findings: List[IocFinding] = []
    alerts_count: int = 0
    warnings_count: int = 0
    notices_count: int = 0
    error_message: Optional[str] = None
    uploaded_to_faraday: bool = False
