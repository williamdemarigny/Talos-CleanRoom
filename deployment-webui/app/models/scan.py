"""Scan state models for security scanning operations."""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ScanStatus(str, Enum):
    """Status of a scan or scan tool."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


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
    custom_modules: Optional[List[str]] = None  # Module IDs for custom profile
    tools: List[ScanToolState] = []
    status: ScanStatus = ScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    faraday_workspace: str = "pentest"


class ScanLogEntry(BaseModel):
    """A log entry from a scan operation."""
    timestamp: datetime
    tool: Optional[str] = None  # None for general messages
    level: str  # info, warn, error
    message: str


class ScanRequest(BaseModel):
    """Request to start a scan."""
    target: str
    tools: List[ScanTool]
    profile: ScanProfile = ScanProfile.STANDARD
    custom_modules: Optional[List[str]] = None  # Module IDs for custom profile
