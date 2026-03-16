"""Scan state models for security scanning operations."""

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
    tools: List[ScanToolState] = []
    status: ScanStatus = ScanStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    faraday_workspace: str = "pentest"


class ScanLogEntry(BaseLogEntry):
    """A log entry from a scan operation."""
    tool: Optional[str] = None


# Scan targets: IPs, CIDR, hostnames, comma-separated lists
_TARGET_PATTERN = re.compile(r'^[a-zA-Z0-9.,:\-/_ ]+$')


class ScanRequest(BaseModel):
    """Request to start a scan."""
    target: str
    tools: List[ScanTool]
    profile: ScanProfile = ScanProfile.STANDARD
    custom_modules: Optional[List[str]] = None
    openvas_config: Optional[str] = None
    openvas_families: Optional[List[str]] = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Target must not be empty")
        if not _TARGET_PATTERN.match(v):
            raise ValueError(
                "Target contains invalid characters. "
                "Only alphanumerics, dots, commas, colons, hyphens, slashes, "
                "underscores, and spaces are allowed."
            )
        return v
