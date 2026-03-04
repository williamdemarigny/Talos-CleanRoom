"""Shared base types used across deployment, scan, and IOC scan models.

This module provides common enums, base models, and shared patterns that
are reused across the different service domains to reduce duplication.
"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class BaseStatus(str, Enum):
    """Common status values shared across deployment, scan, and IOC scan.

    Individual services may extend this with domain-specific statuses
    (e.g., MOUNTING, SCANNING, PARSING for IOC scans).
    """
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class BaseLogEntry(BaseModel):
    """Base log entry with common fields.

    Subclasses add domain-specific fields:
    - LogEntry adds step_id (deployment)
    - ScanLogEntry adds tool (scan)
    - IocScanLogEntry uses this as-is
    """
    timestamp: datetime
    level: str  # info, warn, error
    message: str
