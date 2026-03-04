"""Scan state models for security scanning operations."""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

from app.models.common import BaseStatus, BaseLogEntry


class ScanStatus(str, Enum):
    """Status of a scan or scan tool.

    Mirrors BaseStatus values. Kept as a separate enum for backward
    compatibility with existing code that references ScanStatus members
    directly.
    """
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
    custom_modules: Optional[List[str]] = None  # Metasploit module IDs for custom profile
    openvas_config: Optional[str] = None  # OpenVAS config ID for custom preset
    openvas_families: Optional[List[str]] = None  # OpenVAS NVT family names for custom scan
    tools: List[ScanToolState] = []
    status: ScanStatus = ScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    faraday_workspace: str = "pentest"


class ScanLogEntry(BaseLogEntry):
    """A log entry from a scan operation.

    Extends BaseLogEntry with an optional tool field to identify which
    scan tool (nmap, openvas, metasploit) generated the log message.
    """
    tool: Optional[str] = None  # None for general messages


class ScanRequest(BaseModel):
    """Request to start a scan."""
    target: str
    tools: List[ScanTool]
    profile: ScanProfile = ScanProfile.STANDARD
    custom_modules: Optional[List[str]] = None  # Metasploit module IDs for custom profile
    openvas_config: Optional[str] = None  # OpenVAS config ID for custom preset
    openvas_families: Optional[List[str]] = None  # OpenVAS NVT family names for custom scan
