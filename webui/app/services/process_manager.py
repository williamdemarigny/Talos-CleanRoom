"""Process manager — re-exports from talos_common.

All process management logic lives in the shared
``talos_common.services.process_manager`` module.
This file provides backward-compatible imports.
"""

from talos_common.services.process_manager import (  # noqa: F401
    ProcessResult,
    ProcessManager,
)
