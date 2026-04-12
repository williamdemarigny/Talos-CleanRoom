# Portal — Talos CleanRoom

Unified landing page and cross-domain SSO hub for the Talos CleanRoom platform.

## Overview

The Portal is a lightweight FastAPI application that serves as the entry point for all Talos CleanRoom users. It provides:

- **Landing page** with navigation cards to the Deployment Console and Scanning Console
- **Cross-domain SSO** via HMAC-signed one-time code exchange
- **Credentials page** showing passwords for all deployed services

## Tech Stack

- **Backend:** FastAPI 0.109 + Uvicorn
- **Frontend:** Jinja2 + Alpine.js 3.x + Tailwind CSS 3.x (CDN)
- **Auth:** JWT HS256 (8hr expiry), shared key with other apps via `talos_common`

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page |
| GET | `/login` | Login page |
| GET | `/credentials` | Service credentials page |
| POST | `/api/auth/login` | Authenticate and get JWT |
| POST | `/api/auth/logout` | Clear auth cookie |
| GET | `/api/auth/me` | Current user info |
| POST | `/api/auth/redeem-code` | Redeem SSO code for JWT |
| GET | `/api/portal/status` | App link status |

## Running Locally

```bash
pip install -r requirements.txt
pip install -e ../lib/talos-common

export SECRET_KEY="your-secret-key"
uvicorn app.main:app --reload --port 8002
```

## Deployment

Runs in Kubernetes (namespace `portal`), deployed via ArgoCD. Container image built on the Build VM and pushed to Harbor:

```
harbor.knowledgeondemand.net/cleanroom/portal:<version>
```

See `apps/portal/` for K8s manifests and `build-and-push.sh` for the image build script.

## Configuration

Inherits from `talos_common.ConfigBase`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (required) | Shared secret for JWT/SSO — must match all three apps |
| `DEPLOYMENT_CONSOLE_URL` | `https://10.83.3.190:8000` | Deployment Console URL |
| `SCANNING_CONSOLE_URL` | `https://scan.knowledgeondemand.net` | Scanning Console URL |

## User Guide

See the [User Guide](../docs/user-guide/docs/getting-started/login.md) for end-user documentation.
