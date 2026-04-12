# Scanning Console — Talos CleanRoom

Vulnerability scanning, IOC detection, target lab, and reporting application for the Talos CleanRoom platform.

## Overview

The Scanning Console is a FastAPI application that orchestrates security scanning tools and provides a unified interface for:

- **Vulnerability Scanning** — Nmap, OpenVAS, and Metasploit with combined results
- **IOC Scanning** — LOKI-RS file system scanning for malware indicators via SSH/SMB
- **Target Lab** — Deploy Vulhub vulnerable environments for scan testing
- **Reports** — Dashboard, scan detail, hosts, vulnerabilities, compare, audit log
- **Export** — CSV, JSON, and PDF export of scan results
- **Enrichment** — Automatic CVSS/EPSS data enrichment for vulnerabilities
- **Faraday Integration** — Results uploaded to Faraday vulnerability management platform

## Tech Stack

- **Backend:** FastAPI 0.109 + Uvicorn (async)
- **Database:** PostgreSQL 17 via SQLAlchemy async + Alembic migrations
- **Frontend:** Jinja2 + Alpine.js 3.x + Tailwind CSS 3.x (CDN)
- **Auth:** JWT HS256 (8hr expiry), shared key with other apps via `talos_common`
- **Real-time:** WebSocket + REST polling fallback

## Routes

| Prefix | Description |
|--------|-------------|
| `/api/auth` | Login, logout, SSO code exchange |
| `/api/scan` | Vulnerability scan start/abort/status/history/logs |
| `/api/ioc-scan` | IOC scan start/abort/status/history/logs |
| `/api/target-lab` | Vulhub catalog, deploy/destroy targets, capacity |
| `/api/reports` | Summary, scan detail, hosts, vulnerabilities, compare, audit |
| `/api/export` | CSV/JSON/PDF export, compliance reports |
| `/ws/scan` | Real-time scan progress WebSocket |
| `/ws/ioc-scan` | Real-time IOC scan progress WebSocket |

## Running Locally

```bash
pip install -r requirements.txt
pip install -e ../lib/talos-common

export SECRET_KEY="your-secret-key"
export DATABASE_URL="postgresql+asyncpg://cleanroom:password@localhost:5432/cleanroom"

# Run database migrations
alembic upgrade head

# Start the app
uvicorn app.main:app --reload --port 8001
```

Requires a running PostgreSQL instance and access to K8s cluster (for kubectl-based tool execution).

## Deployment

Runs in Kubernetes (namespace `scanning-console`), deployed via ArgoCD. Container image built on the Build VM and pushed to Harbor:

```
harbor.knowledgeondemand.net/cleanroom/scanning-console:<version>
```

See `apps/scanning-console/` for K8s manifests and `build-and-push.sh` for the image build script.

Database migrations run automatically via an Alembic init container on pod startup.

## Configuration

Inherits from `talos_common.ConfigBase`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (required) | Shared secret for JWT/SSO — must match all three apps |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `TARGET_LAB_ENABLED` | `false` | Enable/disable Vulhub target lab feature |

## Database Schema

Managed by Alembic. Key tables (see `app/db/models.py`):

- `scans` — Scan metadata (target, profile, status, timestamps)
- `hosts` — Discovered hosts with OS and hostname info
- `vulnerabilities` — Findings with severity, CVSS, EPSS, CVE, remediation status
- `ioc_findings` — IOC scan findings with severity, file path, matched rules
- `faraday_sync_log` — Faraday upload tracking with retry queue
- `audit_log` — User action audit trail

## User Guide

See the [User Guide](../docs/user-guide/docs/scanning/vulnerability-scan.md) for end-user documentation.
