"""Authentication API router — re-exports from talos_common.

The shared router in ``talos_common.routers.auth`` provides login/logout/me
endpoints. This file re-exports the router for backward compatibility.
"""

from talos_common.routers.auth import router  # noqa: F401
