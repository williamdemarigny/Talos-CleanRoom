# talos-common

Shared Python library for Talos CleanRoom applications (Deployment Console, Scanning Console, Portal).

## Exported Modules

| Module | Contents |
|--------|----------|
| `talos_common.config_base` | `BaseAppSettings` — shared auth/crypto fields with derived key properties |
| `talos_common.auth` | JWT create/decode, password hashing, `get_current_user` dependency |
| `talos_common.models.common` | `BaseStatus` enum, `BaseLogEntry` Pydantic model |
| `talos_common.services.process_manager` | `ProcessManager`, `ProcessResult` — async subprocess execution |
| `talos_common.services.kubectl_utils` | `KubernetesHelper` — kubectl command wrappers |
| `talos_common.services.base_service` | `BaseServiceMixin` — logging, polling, connectivity checks |
| `talos_common.routers.auth` | Login/logout/me API endpoints |
| `talos_common.routers.exchange` | One-time code redemption endpoint (cross-domain auth) |
| `talos_common.routers.ws_manager` | `ConnectionManager`, `create_message`, `make_broadcast_callback` |
| `talos_common.static/js/` | `app.js` (auth + auto-redeem), `utils.js`, `websocket-base.js` |
| `talos_common.templates/` | `components.html` (Jinja2 macros), `login.html` |

## Installation

**Development (editable):**
```bash
pip install -e lib/talos-common
```

**Docker (in Dockerfile):**
```dockerfile
COPY lib/talos-common /tmp/talos-common
RUN pip install /tmp/talos-common
```

## Usage

Each app must call `talos_common.init()` at startup with its settings getter:

```python
import talos_common
from app.config import get_settings

talos_common.init(get_settings)
```

Then shared modules resolve settings automatically via `Depends(talos_common.get_settings)`.

### Inheriting BaseAppSettings

Each app defines its own settings class inheriting shared auth fields:

```python
from talos_common.config_base import BaseAppSettings

class Settings(BaseAppSettings):
    # App-specific fields
    repo_root: Path = Path("/repo")
    master_node: str = "talos-CleanRoom-master-01.knowledgeondemand.net"
```

`BaseAppSettings` provides: `secret_key`, `admin_username`, `admin_password_hash`, `access_token_expire_hours`, plus derived key properties (`jwt_signing_key`, `code_exchange_key`, `fernet_key`).

### Including shared routers

```python
from talos_common.routers.auth import router as auth_router
from talos_common.routers.exchange import router as exchange_router

app.include_router(auth_router, prefix="/api/auth")
app.include_router(exchange_router, prefix="/api/auth")
```
