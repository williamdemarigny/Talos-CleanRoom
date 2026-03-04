# SecureCodeBox WebUI Integration — Proposed Plan

## Context

The Deployment WebUI is the primary user interaction portal. SecureCodeBox is already deployed in the cluster (`securecodebox-system` namespace) with an operator (v5.5.0) and Nmap scanner, but it's only accessible via `kubectl`. Users need a WebUI page to create, monitor, and view results from SecureCodeBox scans without touching kubectl.

**Key difference from existing Scan page**: The existing Scan page runs scans **imperatively** — the WebUI creates pods, monitors subprocesses, and uploads to Faraday. SecureCodeBox is **declarative** — you create Scan/ScheduledScan CRDs and the K8s operator manages the lifecycle. The backend is simpler (short kubectl calls, polling, no subprocess streaming).

## Files to Create (5 new files)

| File | Purpose |
|------|---------|
| `app/models/auto_scan.py` | Pydantic models for CRD data |
| `app/services/auto_scan_service.py` | kubectl CRD management service |
| `app/routers/auto_scan.py` | REST API + WebSocket endpoint |
| `templates/auto_scan.html` | Jinja2 page template |
| `static/js/auto_scan.js` | Alpine.js component |

## Files to Modify (2 files)

| File | Line | Change |
|------|------|--------|
| `app/main.py` | 10 | Add `auto_scan` to router imports |
| `app/main.py` | after 35 | Add `app.include_router(auto_scan.router, prefix="/api/auto-scan", tags=["Auto Scan"])` |
| `app/main.py` | after 102 | Add `/auto-scan` page route (after ioc_scan_page) |
| `templates/base.html` | after 39 | Add "Auto Scan" nav link (between IOC Scan and Logs) |

## Step 1: Models (`app/models/auto_scan.py`)

Enums and Pydantic models mapping to SecureCodeBox CRD structures:

- `AutoScanStatus` enum: `Pending`, `Scanning`, `ParseResult`, `Done`, `Errored`, `Unknown`
- `FindingSeverity` enum: `high`, `medium`, `low`, `informational`
- `ScanTypeInfo`: name, images (from `kubectl get scantypes -o json`)
- `AutoScanInfo`: name, scan_type, parameters[], status, created_at, finished_at, findings_count
- `ScheduledScanInfo`: name, scan_type, parameters[], interval, last_scheduled, findings_count
- `FindingInfo`: name, scan_name, category, severity, description, location, port, service, attributes
- `CreateScanRequest`: name, scan_type, parameters[]
- `CreateScheduledScanRequest`: name, scan_type, parameters[], interval
- `AutoScanLogEntry`: timestamp, level, message

## Step 2: Service (`app/services/auto_scan_service.py`)

Singleton dataclass following `ioc_scan_service.py` pattern. Uses `ProcessManager.run_command_simple()` for all kubectl calls (no streaming needed).

**ScanType operations:**
- `get_scan_types()` → `kubectl get scantypes -n securecodebox-system -o json` → parse items into `ScanTypeInfo[]`

**Scan CRUD:**
- `create_scan(request)` → generate Scan CRD YAML → `bash -c "cat <<'EOF' | kubectl apply -f -\n...\nEOF"` (heredoc pattern — `run_command_simple` has no stdin support)
- `get_scans()` → `kubectl get scans -n securecodebox-system -o json` → parse into `AutoScanInfo[]`
- `delete_scan(name)` → `kubectl delete scan {name} -n securecodebox-system --ignore-not-found`

**ScheduledScan CRUD:**
- `create_scheduled_scan(request)` → generate ScheduledScan CRD YAML → kubectl apply
- `get_scheduled_scans()` → `kubectl get scheduledscans -n securecodebox-system -o json`
- `delete_scheduled_scan(name)` → kubectl delete

**Findings:**
- `get_findings(scan_name=None)` → `kubectl get findings -n securecodebox-system -o json [-l securecodebox.io/scan-name={name}]`

**Helpers:**
- `_parse_k8s_list(output)` → parse `kubectl -o json` list output
- `_map_status(state)` → map CRD state string to AutoScanStatus enum
- Name sanitization: `re.sub(r'[^a-z0-9-]', '-', name.lower())` for K8s DNS compatibility
- Caching: `_cached_scans`, `_cached_scheduled`, `_cached_scan_types` — returned on kubectl failure
- Log callback for WebSocket broadcast
- **Namespace constant:** `SCB_NAMESPACE = "securecodebox-system"`

## Step 3: Router (`app/routers/auto_scan.py`)

Follow `routers/ioc_scan.py` pattern exactly.

**Connection Manager:** `AutoScanConnectionManager` with `connect/disconnect/broadcast`

**REST endpoints (all require JWT auth):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/scan-types` | List installed scanner types |
| GET | `/scans` | List all Scan CRDs |
| POST | `/scans` | Create one-time scan |
| DELETE | `/scans/{name}` | Delete a scan |
| GET | `/scheduled-scans` | List ScheduledScan CRDs |
| POST | `/scheduled-scans` | Create scheduled scan |
| DELETE | `/scheduled-scans/{name}` | Delete scheduled scan |
| GET | `/findings` | Get findings (optional `?scan_name=` filter) |
| GET | `/logs` | Get service operation logs |

**WebSocket:** `WS /api/auto-scan/ws`
- Auth via token cookie or query param (same as `ioc_scan.py`)
- On connect: send `auto_scan_initial_state` with scans, scheduled_scans, scan_types, recent logs
- Broadcasts: `auto_scan_log` from service log_callback
- Ping/pong keepalive

## Step 4: Modify `app/main.py`

1. Line 10: `from app.routers import auth, deployment, config, websocket, scan, ioc_scan, auto_scan`
2. After line 35: `app.include_router(auto_scan.router, prefix="/api/auto-scan", tags=["Auto Scan"])`
3. After line 102: Page route `/auto-scan` → renders `auto_scan.html` with `page="auto_scan"`

## Step 5: Modify `templates/base.html`

Add nav link after IOC Scan (line 39), before Logs (line 40):
```html
<a href="/auto-scan" class="{% if page == 'auto_scan' %}bg-gray-900 text-white{% else %}text-gray-300 hover:bg-gray-700 hover:text-white{% endif %} px-3 py-2 rounded-md text-sm font-medium">
    Auto Scan
</a>
```

## Step 6: Template (`templates/auto_scan.html`)

Extends `base.html`. Single `x-data="autoScanManager()"` Alpine.js component.

**4 sub-tabs within the page:**

1. **Create Scan** — Scanner type dropdown, scan name, parameters textarea (one per line), scheduled toggle with interval selector, quick preset buttons (Quick Nmap / Service Scan / Network Discovery), create button with validation
2. **Active Scans** — Table of Pending/Scanning/ParseResult scans with status badges, delete buttons, badge count on tab
3. **Scan History** — Table of Done/Errored scans, click to expand findings, findings sub-table with severity badges
4. **Scheduled Scans** — Table of ScheduledScan CRDs with interval, last run, delete button, badge count on tab

**Activity Log panel** (below tabs): log display with auto-scroll, level coloring (same pattern as scan.html)

**Connection status indicator**: fixed bottom-right green/red badge

## Step 7: JavaScript (`static/js/auto_scan.js`)

Alpine.js `autoScanManager()` following `scanManager()` pattern.

**State:** activeTab, form fields (scanName, scanType, parameters, isScheduled, interval), data arrays (scanTypes, scans, scheduledScans), expandedScan/expandedFindings for detail drill-down, logs, WebSocket state

**Key methods:** init, refreshAll, pollUpdates (10s interval), createScan, deleteScan, deleteScheduledScan, toggleScanDetails (lazy-loads findings), connectWebSocket (auto-reconnect), status/severity badge helpers

**Polling: 10 seconds** (background K8s jobs, not real-time interactive)

## How It Fits With the Existing Scan Stack

| Layer | Tools | Triggered By | Purpose |
|-------|-------|-------------|---------|
| **WebUI Interactive** (Scan tab) | Nmap, OpenVAS, Metasploit | User on-demand | Real-time analyst-driven scanning with Faraday upload |
| **WebUI Automated** (Auto Scan tab) | SecureCodeBox (Nmap + future scanners) | User creates CRDs | Scheduled/recurring background scanning via K8s operator |
| **IOC Detection** (IOC Scan tab) | LOKI-RS | User on-demand | Filesystem-level IOC detection on remote mounts |

The existing **Scan** tab is for interactive, one-off investigations with real-time WebSocket feedback. **Auto Scan** is for setting up automated, recurring security checks that run in the background. They complement each other — an analyst might use the Scan tab for deep investigation after Auto Scan discovers something interesting.

## Future Enhancements

- Add more SecureCodeBox scanners (Nikto, ZAP, Nuclei, Trivy) as ArgoCD applications — they automatically appear in the Auto Scan scanner type dropdown
- Add a Faraday persistence hook to SecureCodeBox to unify findings in one place
- Add cascading scan support (Nmap finds open ports → auto-trigger Nikto on web services)

## Verification

1. Start the WebUI service
2. Verify "Auto Scan" appears in nav between "IOC Scan" and "Logs"
3. Navigate to `/auto-scan` — page loads with Create Scan tab
4. Verify scan types load (should show `nmap` if SecureCodeBox is deployed)
5. Create a test scan: name=`test-scan`, type=`nmap`, parameters=`-F` and `scanme.nmap.org`
6. Verify scan appears in Active Scans tab with Pending/Scanning status
7. Wait for completion → moves to Scan History with findings count
8. Expand scan to view findings
9. Create a scheduled scan with 24h interval → appears in Scheduled Scans tab
10. Delete a scan → removed from list
11. Verify WebSocket indicator shows green
12. Verify activity log shows operation entries
