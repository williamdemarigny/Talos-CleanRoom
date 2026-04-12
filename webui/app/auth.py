"""Authentication module — re-exports from talos_common.

All auth logic lives in the shared ``talos_common.auth`` module.
This file provides backward-compatible imports so existing code
(``from app.auth import get_current_user``) continues to work.
"""

from talos_common.auth import (  # noqa: F401
    pwd_context,
    security,
    LOCAL_ALGORITHM as ALGORITHM,
    verify_password,
    get_password_hash,
    create_access_token,
    decode_token,
    authenticate_user,
    get_current_user,
    get_current_user_optional,
)
