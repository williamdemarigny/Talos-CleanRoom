"""Shared base types — re-exports from talos_common.

All common model types live in the shared ``talos_common.models.common``
module. This file provides backward-compatible imports.
"""

from talos_common.models.common import (  # noqa: F401
    BaseStatus,
    BaseLogEntry,
)
