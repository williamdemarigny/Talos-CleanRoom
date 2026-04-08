"""
Capture the remaining 12 screenshots that need either:
- Mock data for transient states (deployment running/failed, scan running, enrichment)
- UI interactions (cleanup dialog, remediation dropdown, validation error)
- Live operations (scan detail page retry)

Run after capture.py has captured the static screenshots.

Usage:
    python capture_remaining.py --scanning-password "wGOAUYX2P8SLbPyD"
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext, Route

PORTAL_URL = "https://cleanroom.knowledgeondemand.net"
DEPLOYMENT_URL = "http://10.83.3.190:8000"
SCANNING_URL = "https://scan.knowledgeondemand.net"
USERNAME = "admin"
PASSWORD = "admin"
SCANNING_PASSWORD = "admin"

VIEWPORT = {"width": 1280, "height": 800}
DEVICE_SCALE = 2


async def login(page: Page, base_url: str, password: str = None) -> bool:
    """Log in via API, fallback to browser form."""
    pw = password or PASSWORD
    try:
        response = await page.request.post(
            f"{base_url}/api/auth/login",
            data=json.dumps({"username": USERNAME, "password": pw}),
            headers={"Content-Type": "application/json"},
        )
        if response.status == 200:
            data = await response.json()
            token = data.get("access_token", "")
            await page.goto(base_url, wait_until="networkidle")
            await page.evaluate(f"localStorage.setItem('access_token', '{token}')")
            return True
    except Exception:
        pass

    # Fallback: browser form
    try:
        await page.goto(f"{base_url}/login", wait_until="networkidle")
        for user_sel, pass_sel in [("#username", "#password"), ("#login-username", "#login-password")]:
            try:
                el = page.locator(user_sel)
                if await el.is_visible(timeout=2000):
                    await el.fill(USERNAME)
                    await page.locator(pass_sel).fill(pw)
                    await page.click("button[type=submit]")
                    await page.wait_for_timeout(2000)
                    if "/login" not in page.url:
                        return True
                    break
            except Exception:
                continue
    except Exception:
        pass
    print(f"  [ERROR] Could not log in to {base_url}")
    return False


async def capture(page: Page, path: Path, name: str, full_page: bool = False) -> None:
    """Take a screenshot."""
    filepath = path / name
    filepath.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(filepath), type="jpeg", quality=85, full_page=full_page)
    print(f"  [OK] {name}")


async def wait_for_alpine(page: Page) -> None:
    try:
        await page.wait_for_function("typeof Alpine !== 'undefined'", timeout=5000)
        await page.wait_for_timeout(500)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Mocked deployment states
# ---------------------------------------------------------------------------

def _make_steps(current_step: int, failed: bool = False):
    """Generate deployment steps array."""
    step_names = [
        "Validate Git Repository", "Check Dependencies", "Terraform Deploy",
        "Wait for VMs to Boot", "Generate Talos Config", "Apply Talos Configurations",
        "Verify Cluster Health", "Get Kubeconfig", "Install ArgoCD",
        "Deploy Infrastructure Stack", "Enable ArgoCD Self-Management",
        "Deploy OpenVAS", "Deploy Faraday", "Deploy Metasploit",
        "Deploy Threat Dragon", "Deploy Harbor Registry", "Configure Integrations",
        "Generate & Apply Secrets", "Commit & Push Secrets", "Deploy Build VM",
        "Build & Push Container Images", "Deploy CleanRoom Applications",
        "Apply Network Policies",
    ]
    steps = []
    for i, name in enumerate(step_names):
        if i < current_step:
            status = "success"
        elif i == current_step:
            status = "failed" if failed else "running"
        else:
            status = "pending"
        steps.append({
            "id": i, "name": f"step_{i}", "description": name,
            "status": status,
            "started_at": "2025-01-01T12:00:00" if status != "pending" else None,
            "completed_at": "2025-01-01T12:01:00" if status == "success" else None,
            "error_message": "Connection timed out waiting for node 10.83.3.10 to respond"
            if status == "failed" else None,
        })
    return steps


async def capture_deployment_mocked(context: BrowserContext, output: Path) -> None:
    """Capture deployment transient states using route interception."""
    print("\n=== Deployment (Mocked States) ===")
    deploy = DEPLOYMENT_URL

    # --- Idle state ---
    page = await context.new_page()
    idle_state = {
        "id": "", "status": "idle", "current_step": 0,
        "steps": _make_steps(0), "started_at": None,
        "completed_at": None, "error_message": None,
    }
    # Override all steps to pending for idle
    for s in idle_state["steps"]:
        s["status"] = "pending"
        s["started_at"] = None
        s["completed_at"] = None

    async def handle_idle(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(idle_state))
    await page.route("**/api/deployment/status", handle_idle)
    await page.route("**/api/deployment/logs**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="[]"))
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, deploy)
    await page.goto(f"{deploy}/deployment", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)
    await capture(page, output / "deployment", "deployment-idle-start.jpg", full_page=True)
    await page.close()

    # --- Running at step 9 ---
    page = await context.new_page()
    running_state = {
        "id": "deploy-001", "status": "running", "current_step": 9,
        "steps": _make_steps(9),
        "started_at": "2025-01-01T12:00:00",
        "completed_at": None, "error_message": None,
    }
    mock_logs = [
        {"step_id": 9, "level": "INFO", "message": "Deploying MetalLB via Helm...",
         "timestamp": "2025-01-01T12:05:00"},
        {"step_id": 9, "level": "INFO", "message": "Waiting for MetalLB pods to be ready...",
         "timestamp": "2025-01-01T12:05:10"},
        {"step_id": 9, "level": "INFO", "message": "Deploying cert-manager v1.19.3...",
         "timestamp": "2025-01-01T12:05:30"},
        {"step_id": 9, "level": "INFO", "message": "Deploying Traefik ingress controller...",
         "timestamp": "2025-01-01T12:06:00"},
        {"step_id": 9, "level": "INFO", "message": "Configuring Ceph CSI storage driver...",
         "timestamp": "2025-01-01T12:06:30"},
    ]

    async def handle_running(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(running_state))
    async def handle_logs(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(mock_logs))

    await page.route("**/api/deployment/status", handle_running)
    await page.route("**/api/deployment/logs**", handle_logs)
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, deploy)
    await page.goto(f"{deploy}/deployment", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1500)
    await capture(page, output / "deployment", "deployment-running-midflight.jpg", full_page=True)
    await page.close()

    # --- Failed at step 5 ---
    page = await context.new_page()
    failed_state = {
        "id": "deploy-001", "status": "failed", "current_step": 5,
        "steps": _make_steps(5, failed=True),
        "started_at": "2025-01-01T12:00:00",
        "completed_at": None, "error_message": "Step 5 failed",
    }

    async def handle_failed(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(failed_state))

    await page.route("**/api/deployment/status", handle_failed)
    await page.route("**/api/deployment/logs**", handle_logs)
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, deploy)
    await page.goto(f"{deploy}/deployment", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1500)
    await capture(page, output / "deployment", "deployment-failed-resume-skip.jpg", full_page=True)
    await page.close()


async def capture_deployment_interactions(context: BrowserContext, output: Path) -> None:
    """Capture deployment screenshots requiring UI interaction (non-destructive)."""
    print("\n=== Deployment (Interactions) ===")
    deploy = DEPLOYMENT_URL

    page = await context.new_page()
    await login(page, deploy)

    # Cleanup confirmation dialog — click button, capture dialog, then dismiss
    await page.goto(deploy, wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)

    # Override window.confirm to capture the state with a dialog visible
    # Instead, look for the cleanup button and use Alpine to show a confirm state
    try:
        # Intercept confirm() to always return false (cancel)
        await page.evaluate("window.confirm = () => false")
        cleanup_btn = page.locator("text=Run Cleanup").first
        if await cleanup_btn.is_visible(timeout=3000):
            await cleanup_btn.click()
            await page.wait_for_timeout(500)
            await capture(page, output / "deployment", "deployment-cleanup-confirm.jpg")
            print("  [OK] deployment-cleanup-confirm.jpg")
        else:
            print("  [WARN] Cleanup button not found — may need different state")
    except Exception as e:
        print(f"  [WARN] Could not capture cleanup dialog: {e}")

    # Validation error — try to find the validation endpoint and check if we can show errors
    try:
        await page.goto(f"{deploy}/config", wait_until="networkidle")
        await wait_for_alpine(page)
        await page.wait_for_timeout(500)

        # Inject a mock validation error via Alpine state
        await page.evaluate("""() => {
            const el = document.querySelector('[x-data]');
            if (el && el._x_dataStack) {
                const data = Alpine.$data(el);
                if (data) {
                    data.validationErrors = ['Node talos-CleanRoom-master-01 has invalid MAC address', 'Gateway IP 10.83.3.1 is not reachable'];
                    data.validationWarnings = ['Disk size 50GB may be insufficient for OpenVAS data'];
                    data.configValid = false;
                }
            }
        }""")
        await page.wait_for_timeout(500)
        await capture(page, output / "deployment", "deployment-config-validation-error.jpg", full_page=True)
    except Exception as e:
        print(f"  [WARN] Could not capture validation error: {e}")

    await page.close()


# ---------------------------------------------------------------------------
# Mocked scanning states
# ---------------------------------------------------------------------------

async def capture_scanning_mocked(context: BrowserContext, output: Path) -> None:
    """Capture scanning transient states using route interception."""
    print("\n=== Scanning (Mocked States) ===")
    scan = SCANNING_URL

    # --- Scan running ---
    # Use elasticsearch-groovy Vulhub target for realistic screenshots
    es_target = "elasticsearch-groovy.vulhub-elasticsearch-groovy-1434ad.svc.cluster.local:9200"
    page = await context.new_page()
    running_state = {
        "id": "97a676ca", "target": es_target, "profile": "standard",
        "tools": [
            {"tool": "nmap", "status": "completed",
             "started_at": "2026-04-08T14:00:00", "completed_at": "2026-04-08T14:01:30",
             "error_message": None, "findings_count": 3, "uploaded_to_faraday": True},
            {"tool": "openvas", "status": "running",
             "started_at": "2026-04-08T14:01:35", "completed_at": None,
             "error_message": None, "findings_count": 8, "uploaded_to_faraday": False},
            {"tool": "metasploit", "status": "idle",
             "started_at": None, "completed_at": None,
             "error_message": None, "findings_count": 0, "uploaded_to_faraday": False},
        ],
        "status": "running",
        "started_at": "2026-04-08T14:00:00", "completed_at": None,
    }
    mock_logs = [
        {"tool": "nmap", "level": "INFO", "message": f"Starting Nmap scan against {es_target}",
         "timestamp": "2026-04-08T14:00:00"},
        {"tool": "nmap", "level": "INFO", "message": "Nmap scan completed: 3 findings (1 host, 1 open port: 9200/tcp Elasticsearch)",
         "timestamp": "2026-04-08T14:01:30"},
        {"tool": "nmap", "level": "INFO", "message": "Results uploaded to Faraday workspace 'pentest'",
         "timestamp": "2026-04-08T14:01:35"},
        {"tool": "openvas", "level": "INFO", "message": "OpenVAS scan started with Full and Fast config",
         "timestamp": "2026-04-08T14:01:40"},
        {"tool": "openvas", "level": "INFO", "message": "Scan progress: 34% | Active hosts: 1 | Results: 8 | Elapsed: 4m 12s",
         "timestamp": "2026-04-08T14:05:52"},
    ]

    async def handle_status(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(running_state))
    async def handle_logs(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(mock_logs))
    async def handle_history(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps([]))

    await page.route("**/api/scan/status", handle_status)
    await page.route("**/api/scan/logs**", handle_logs)
    await page.route("**/api/scan/history**", handle_history)
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, scan, SCANNING_PASSWORD)
    await page.goto(f"{scan}/scan", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1500)
    await capture(page, output / "scanning", "scanning-scan-running.jpg", full_page=True)
    await page.close()

    # --- Scan completed with enrichment ---
    page = await context.new_page()
    completed_state = {
        "id": "97a676ca", "target": es_target, "profile": "standard",
        "tools": [
            {"tool": "nmap", "status": "completed",
             "started_at": "2026-04-08T14:00:00", "completed_at": "2026-04-08T14:01:30",
             "error_message": None, "findings_count": 3, "uploaded_to_faraday": True},
            {"tool": "openvas", "status": "completed",
             "started_at": "2026-04-08T14:01:35", "completed_at": "2026-04-08T14:38:00",
             "error_message": None, "findings_count": 14, "uploaded_to_faraday": True},
            {"tool": "metasploit", "status": "completed",
             "started_at": "2026-04-08T14:38:05", "completed_at": "2026-04-08T14:42:30",
             "error_message": None, "findings_count": 2, "uploaded_to_faraday": True},
        ],
        "status": "completed",
        "started_at": "2026-04-08T14:00:00", "completed_at": "2026-04-08T14:42:30",
    }

    async def handle_completed(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(completed_state))

    await page.route("**/api/scan/status", handle_completed)
    await page.route("**/api/scan/logs**", handle_logs)
    await page.route("**/api/scan/history**", handle_history)
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, scan, SCANNING_PASSWORD)
    await page.goto(f"{scan}/scan", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1500)
    await capture(page, output / "scanning", "scanning-scan-completed.jpg", full_page=True)
    await page.close()

    # --- Enrichment in progress ---
    page = await context.new_page()
    await page.route("**/api/scan/status", handle_completed)
    await page.route("**/api/scan/logs**", handle_logs)
    await page.route("**/api/scan/history**", handle_history)
    await page.route("**/ws/**", lambda r: r.abort())

    # Mock enrichment status
    enrichment_status = {
        "running": True, "scan_id": "97a676ca",
        "progress": 11, "total": 19, "status": "running",
    }
    await page.route("**/api/enrichment/status**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(enrichment_status)))

    await login(page, scan, SCANNING_PASSWORD)
    await page.goto(f"{scan}/scan", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)

    # Inject enrichment progress bar state via Alpine
    await page.evaluate("""() => {
        const el = document.querySelector('[x-data]');
        if (el) {
            const data = Alpine.$data(el);
            if (data) {
                data.enrichmentStatus = 'running';
                data.enrichmentProgress = 11;
                data.enrichmentTotal = 19;
            }
        }
    }""")
    await page.wait_for_timeout(500)
    await capture(page, output / "scanning", "scanning-enrichment-progress.jpg", full_page=True)
    await page.close()


async def capture_target_lab_mocked(context: BrowserContext, output: Path) -> None:
    """Capture Target Lab screenshots using route interception."""
    print("\n=== Target Lab (Mocked States) ===")
    scan = SCANNING_URL

    mock_catalog = [
        {"env_id": "elasticsearch-groovy", "name": "Elasticsearch Groovy RCE",
         "cve": "CVE-2015-1427", "category": "rce", "difficulty": "easy", "tier": "tier1",
         "description": "Remote code execution via Groovy scripting engine in Elasticsearch 1.3.x before 1.3.8 and 1.4.x before 1.4.3.",
         "services": ["9200/tcp"], "recommended_scan": {"tools": ["nmap", "openvas", "metasploit"], "profile": "standard"}},
        {"env_id": "apache-cve-2021-41773", "name": "Apache 2.4.49 Path Traversal",
         "cve": "CVE-2021-41773", "category": "web", "difficulty": "easy", "tier": "tier1",
         "description": "Path traversal and RCE via crafted URI in Apache HTTP Server 2.4.49.",
         "services": ["80/tcp"], "recommended_scan": {"tools": ["nmap", "openvas"], "profile": "quick"}},
        {"env_id": "log4j-cve-2021-44228", "name": "Log4Shell (Log4j RCE)",
         "cve": "CVE-2021-44228", "category": "rce", "difficulty": "medium", "tier": "tier2",
         "description": "Remote code execution via JNDI injection in Apache Log4j 2.x.",
         "services": ["8080/tcp", "8983/tcp"], "recommended_scan": {"tools": ["nmap", "metasploit"], "profile": "standard"}},
        {"env_id": "spring4shell-cve-2022-22965", "name": "Spring4Shell",
         "cve": "CVE-2022-22965", "category": "rce", "difficulty": "medium", "tier": "tier1",
         "description": "RCE via data binding in Spring Framework on JDK 9+.",
         "services": ["8080/tcp"], "recommended_scan": {"tools": ["nmap", "openvas"], "profile": "standard"}},
        {"env_id": "mysql-cve-2012-2122", "name": "MySQL Auth Bypass",
         "cve": "CVE-2012-2122", "category": "database", "difficulty": "easy", "tier": "tier1",
         "description": "Authentication bypass in MySQL/MariaDB due to improper password comparison.",
         "services": ["3306/tcp"], "recommended_scan": {"tools": ["nmap", "metasploit"], "profile": "quick"}},
        {"env_id": "redis-cve-2022-0543", "name": "Redis Lua Sandbox Escape",
         "cve": "CVE-2022-0543", "category": "database", "difficulty": "hard", "tier": "tier2",
         "description": "Lua sandbox escape leading to RCE in Redis on Debian-based systems.",
         "services": ["6379/tcp"], "recommended_scan": {"tools": ["nmap", "metasploit"], "profile": "standard"}},
    ]

    mock_targets_active = [
        {"id": "1434ad", "env_id": "elasticsearch-groovy", "name": "Elasticsearch Groovy RCE",
         "cve_id": "CVE-2015-1427", "category": "rce",
         "service_endpoint": "elasticsearch-groovy.vulhub-elasticsearch-groovy-1434ad.svc.cluster.local:9200",
         "status": "running",
         "created_at": "2026-04-08T13:45:00", "ttl_expires_at": "2026-04-08T15:45:00",
         "error_message": None},
        {"id": "tgt-002", "env_id": "log4j-cve-2021-44228", "name": "Log4Shell (Log4j RCE)",
         "cve_id": "CVE-2021-44228", "category": "rce",
         "service_endpoint": "10.83.3.220:32002", "status": "deploying",
         "created_at": "2026-04-08T14:05:00", "ttl_expires_at": "2026-04-08T16:05:00",
         "error_message": None},
    ]

    mock_deploy_logs = {
        "tgt-002": [
            {"timestamp": "2026-04-08T14:05:01", "step": "create_namespace", "level": "INFO",
             "message": "Creating namespace target-log4j-cve-2021-44228"},
            {"timestamp": "2026-04-08T14:05:03", "step": "apply_manifests", "level": "INFO",
             "message": "Applying Vulhub manifests for log4j-cve-2021-44228"},
            {"timestamp": "2026-04-08T14:05:08", "step": "wait_ready", "level": "INFO",
             "message": "Waiting for pods to become ready (0/2 ready)..."},
        ],
    }

    # --- Catalog + active targets ---
    page = await context.new_page()

    async def handle_catalog(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(mock_catalog))

    async def handle_targets(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(mock_targets_active))

    async def handle_capacity(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps({"enabled": True, "used": 2, "max": 5}))

    async def handle_deploy_logs(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(mock_deploy_logs))

    await page.route("**/api/target-lab/catalog", handle_catalog)
    await page.route("**/api/target-lab/targets", handle_targets)
    await page.route("**/api/target-lab/capacity", handle_capacity)
    await page.route("**/api/target-lab/deploy-logs**", handle_deploy_logs)
    await page.route("**/ws/**", lambda r: r.abort())

    await login(page, scan, SCANNING_PASSWORD)
    await page.goto(f"{scan}/target-lab", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1500)
    await capture(page, output / "scanning", "scanning-target-lab-active.jpg", full_page=True)

    # Expand the deploying target's logs
    try:
        logs_btn = page.locator("button:has-text('Logs')").first
        if await logs_btn.is_visible(timeout=3000):
            await logs_btn.click()
            await page.wait_for_timeout(800)
            await capture(page, output / "scanning", "scanning-target-lab-deploying.jpg", full_page=True)
    except Exception as e:
        print(f"  [WARN] Could not expand deploy logs: {e}")

    await page.close()


async def capture_scanning_interactions(context: BrowserContext, output: Path) -> None:
    """Capture scanning screenshots requiring real UI interaction."""
    print("\n=== Scanning (Interactions) ===")
    scan = SCANNING_URL

    page = await context.new_page()
    await login(page, scan, SCANNING_PASSWORD)

    # Remediation dropdown — navigate to vulns, click on one
    await page.goto(f"{scan}/reports/vulns", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)

    try:
        # Look for a remediation status dropdown/select or a clickable vuln row
        # Try clicking the first remediation dropdown
        remediation_el = page.locator("select, [x-model*='remediation'], .remediation-dropdown").first
        if await remediation_el.is_visible(timeout=3000):
            await remediation_el.click()
            await page.wait_for_timeout(300)
            await capture(page, output / "scanning", "scanning-vuln-remediation.jpg", full_page=True)
        else:
            # Fallback: just capture the vulns page (which already shows remediation status column)
            await capture(page, output / "scanning", "scanning-vuln-remediation.jpg", full_page=True)
            print("  [INFO] Captured vulns page as remediation screenshot (no dropdown found)")
    except Exception as e:
        # Final fallback
        await capture(page, output / "scanning", "scanning-vuln-remediation.jpg", full_page=True)
        print(f"  [INFO] Captured vulns page as fallback: {e}")

    # Scan detail page — navigate directly to known scan ID
    scan_detail_id = os.environ.get("SCAN_DETAIL_ID", "97a676ca")
    await page.goto(f"{scan}/reports/scan/{scan_detail_id}", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)
    await capture(page, output / "reports", "reports-scan-detail.jpg", full_page=True)

    await page.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    global PORTAL_URL, DEPLOYMENT_URL, SCANNING_URL, USERNAME, PASSWORD, SCANNING_PASSWORD
    DEPLOYMENT_URL = args.deployment.rstrip("/")
    SCANNING_URL = args.scanning.rstrip("/")
    USERNAME = args.username
    PASSWORD = args.password
    SCANNING_PASSWORD = args.scanning_password or PASSWORD

    output = Path(args.output)

    print(f"Capturing remaining screenshots to {output.resolve()}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            ignore_https_errors=True,
        )

        await capture_deployment_mocked(context, output)
        await capture_deployment_interactions(context, output)
        await capture_scanning_mocked(context, output)
        await capture_target_lab_mocked(context, output)
        await capture_scanning_interactions(context, output)

        await context.close()
        await browser.close()

    print("\nDone! Remaining screenshots that need live operations:")
    print("  - scanning-ioc-running.jpg (run an IOC scan)")
    print("  - scanning-ioc-findings.jpg (need IOC scan results)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture remaining screenshots")
    parser.add_argument("--deployment", default=DEPLOYMENT_URL)
    parser.add_argument("--scanning", default=SCANNING_URL)
    parser.add_argument("--output", default="../docs/img")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--scanning-password", default=None)
    parser.add_argument("--scan-detail-id", default="97a676ca", help="Scan ID for detail screenshot")
    args = parser.parse_args()

    if args.scan_detail_id:
        os.environ["SCAN_DETAIL_ID"] = args.scan_detail_id

    asyncio.run(main(args))
