"""IOC scan state models for LOKI-RS host-based IOC scanning."""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class MountType(str, Enum):
    """Filesystem mount protocol for remote scanning."""
    SSH = "ssh"
    SMB = "smb"


class IocScanStatus(str, Enum):
    """Status of an IOC scan operation."""
    IDLE = "idle"
    MOUNTING = "mounting"
    SCANNING = "scanning"
    PARSING = "parsing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class IocSeverity(str, Enum):
    """LOKI-RS finding severity levels."""
    NOTICE = "notice"     # score >= 40
    WARNING = "warning"   # score >= 60
    ALERT = "alert"       # score >= 80


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


class IocScanLogEntry(BaseModel):
    """A log entry from an IOC scan operation."""
    timestamp: datetime
    level: str  # info, warn, error
    message: str


class IocScanRequest(BaseModel):
    """Request to start an IOC scan."""
    target: str
    mount_type: MountType
    scan_path: str = "/"
    # SSH credentials
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_key: Optional[str] = None
    # SMB credentials
    smb_share: Optional[str] = None
    smb_username: Optional[str] = None
    smb_password: Optional[str] = None
    smb_domain: Optional[str] = None
    # Scan options
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
