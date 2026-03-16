"""WebSocket connection manager — re-exports from talos_common.

All WebSocket manager logic lives in the shared
``talos_common.routers.ws_manager`` module.
This file provides backward-compatible imports.
"""

from talos_common.routers.ws_manager import (  # noqa: F401
    ConnectionManager,
    create_message,
    make_broadcast_callback,
)
