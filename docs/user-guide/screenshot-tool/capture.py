"""
Talos CleanRoom — Screenshot Capture Tool

Captures screenshots of all three web apps for the user guide documentation.
Run against a live deployment for real screenshots, or use mock_data for transient states.

Usage:
    python capture.py --portal https://cleanroom.knowledgeondemand.net \
                      --deployment https://10.83.3.190:8000 \
                      --scanning https://scan.knowledgeondemand.net \
                      --output ../docs/img

Prerequisites:
    pip install -r requirements.txt
    python -m playwright install chromium
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

# Default URLs
PORTAL_URL = "https://cleanroom.knowledgeondemand.net"
DEPLOYMENT_URL = "http://10.83.3.190:8000"
SCANNING_URL = "https://scan.knowledgeondemand.net"

# Credentials
USERNAME = "admin"
PASSWORD = "admin"

# Viewport
VIEWPORT = {"width": 1280, "height": 800}
DEVICE_SCALE = 2


async def login(page: Page, base_url: str, password: str = None) -> bool:
    """Log in to an app via the API, falling back to browser form login.

    Returns True if login succeeded, False otherwise.
    """
    pw = password or PASSWORD

    # Try API login first
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

    # Fallback: browser form login
    print(f"  [INFO] API login failed, trying browser login for {base_url}")
    try:
        await page.goto(f"{base_url}/login", wait_until="networkidle")
        # Try both selector patterns (webui uses #username, scanning-app uses #login-username)
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
    except Exception as e:
        print(f"  [WARN] Browser login also failed: {e}")

    print(f"  [ERROR] Could not log in to {base_url}")
    return False


async def wait_for_alpine(page: Page) -> None:
    """Wait for Alpine.js to initialize on the page."""
    try:
        await page.wait_for_function(
            "typeof Alpine !== 'undefined'", timeout=5000
        )
        await page.wait_for_timeout(500)  # Let Alpine render
    except Exception:
        pass  # Page may not use Alpine


async def capture(page: Page, path: Path, name: str, full_page: bool = False) -> None:
    """Take a screenshot and save it."""
    filepath = path / name
    filepath.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(filepath), type="jpeg", quality=85, full_page=full_page)
    print(f"  [OK] {name}")


# ---------------------------------------------------------------------------
# Phase A: Static captures (no mocking required)
# ---------------------------------------------------------------------------

async def capture_portal(context: BrowserContext, output: Path) -> None:
    """Capture Portal screenshots."""
    print("\n=== Portal ===")
    page = await context.new_page()
    portal = PORTAL_URL

    # 1. Login page (unauthenticated)
    await page.goto(f"{portal}/login", wait_until="networkidle")
    await capture(page, output / "portal", "portal-login-empty.jpg")

    # 2. Login and capture landing page
    await login(page, portal)
    await page.goto(portal, wait_until="networkidle")
    await wait_for_alpine(page)
    await capture(page, output / "portal", "portal-landing-cards.jpg")

    # 3. Credentials page
    await page.goto(f"{portal}/credentials", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)  # Wait for credentials to load
    await capture(page, output / "portal", "portal-credentials-masked.jpg")

    await page.close()


async def capture_deployment(context: BrowserContext, output: Path) -> None:
    """Capture Deployment Console screenshots."""
    print("\n=== Deployment Console ===")
    page = await context.new_page()
    deploy = DEPLOYMENT_URL

    await login(page, deploy)

    # 4. Dashboard
    await page.goto(deploy, wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)
    await capture(page, output / "deployment", "deployment-dashboard-completed.jpg", full_page=True)

    # 5-6. Configuration tabs
    await page.goto(f"{deploy}/config", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "deployment", "deployment-config-terraform.jpg", full_page=True)

    # Try clicking Talos tab
    try:
        talos_tab = page.locator("text=Talos").first
        if await talos_tab.is_visible():
            await talos_tab.click()
            await page.wait_for_timeout(500)
            await capture(page, output / "deployment", "deployment-config-talos.jpg", full_page=True)
    except Exception as e:
        print(f"  [WARN] Could not capture Talos tab: {e}")

    # 7. Deployment page (current state)
    await page.goto(f"{deploy}/deployment", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "deployment", "deployment-completed-banner.jpg", full_page=True)

    # 8. Logs page
    await page.goto(f"{deploy}/logs", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "deployment", "deployment-logs-filters.jpg", full_page=True)

    await page.close()


async def capture_scanning(context: BrowserContext, output: Path) -> None:
    """Capture Scanning Console screenshots."""
    print("\n=== Scanning Console ===")
    page = await context.new_page()
    scan = SCANNING_URL

    await login(page, scan, SCANNING_PASSWORD)

    # 9. Scan config form (empty)
    await page.goto(f"{scan}/scan", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "scanning", "scanning-scan-config-empty.jpg")

    # 10. Profile info panel — try clicking the info toggle
    try:
        info_toggle = page.locator("text=Show what each profile").first
        if await info_toggle.is_visible():
            await info_toggle.click()
            await page.wait_for_timeout(500)
            await capture(page, output / "scanning", "scanning-scan-profile-info.jpg", full_page=True)
    except Exception as e:
        print(f"  [WARN] Could not capture profile info: {e}")

    # 11. Custom profile module picker
    try:
        custom_btn = page.locator("text=Custom").first
        if await custom_btn.is_visible():
            await custom_btn.click()
            await page.wait_for_timeout(500)
            await capture(page, output / "scanning", "scanning-scan-custom-modules.jpg", full_page=True)
    except Exception as e:
        print(f"  [WARN] Could not capture custom modules: {e}")

    # 12-13. IOC Scan forms
    await page.goto(f"{scan}/ioc-scan", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "scanning", "scanning-ioc-ssh.jpg")

    # Switch to SMB
    try:
        smb_option = page.locator("text=SMB").first
        if await smb_option.is_visible():
            await smb_option.click()
            await page.wait_for_timeout(300)
            await capture(page, output / "scanning", "scanning-ioc-smb.jpg")
    except Exception as e:
        print(f"  [WARN] Could not capture SMB form: {e}")

    await page.close()


async def capture_target_lab(context: BrowserContext, output: Path) -> None:
    """Capture Target Lab screenshots."""
    print("\n=== Target Lab ===")
    page = await context.new_page()
    scan = SCANNING_URL

    await login(page, scan, SCANNING_PASSWORD)

    # Target Lab catalog
    await page.goto(f"{scan}/target-lab", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)
    await capture(page, output / "scanning", "scanning-target-lab-catalog.jpg", full_page=True)

    await page.close()


async def capture_reports(context: BrowserContext, output: Path) -> None:
    """Capture Reports screenshots."""
    print("\n=== Reports ===")
    page = await context.new_page()
    scan = SCANNING_URL

    await login(page, scan, SCANNING_PASSWORD)

    # 14. Reports dashboard
    await page.goto(f"{scan}/reports", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(1000)
    await capture(page, output / "reports", "reports-dashboard.jpg", full_page=True)

    # 15. Scan detail — navigate directly to known scan ID if set, else click first
    scan_detail_id = os.environ.get("SCAN_DETAIL_ID", "")
    if scan_detail_id:
        await page.goto(f"{scan}/reports/scan/{scan_detail_id}", wait_until="networkidle")
        await wait_for_alpine(page)
        await page.wait_for_timeout(1000)
        await capture(page, output / "reports", "reports-scan-detail.jpg", full_page=True)
    else:
        try:
            first_detail = page.locator("text=View Details").first
            if await first_detail.is_visible():
                await first_detail.click()
                await page.wait_for_load_state("networkidle")
                await wait_for_alpine(page)
                await page.wait_for_timeout(500)
                await capture(page, output / "reports", "reports-scan-detail.jpg", full_page=True)
        except Exception as e:
            print(f"  [WARN] Could not capture scan detail: {e}")

    # 16. Hosts page
    await page.goto(f"{scan}/reports/hosts", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "reports", "reports-hosts.jpg", full_page=True)

    # 17. Vulnerabilities page
    await page.goto(f"{scan}/reports/vulns", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "reports", "reports-vulns-filters.jpg", full_page=True)

    # 18. Compare page
    await page.goto(f"{scan}/reports/compare", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "reports", "reports-compare-results.jpg", full_page=True)

    # 19. Audit page
    await page.goto(f"{scan}/reports/audit", wait_until="networkidle")
    await wait_for_alpine(page)
    await page.wait_for_timeout(500)
    await capture(page, output / "reports", "reports-audit.jpg", full_page=True)

    await page.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    global PORTAL_URL, DEPLOYMENT_URL, SCANNING_URL, USERNAME, PASSWORD, SCANNING_PASSWORD
    PORTAL_URL = args.portal.rstrip("/")
    DEPLOYMENT_URL = args.deployment.rstrip("/")
    SCANNING_URL = args.scanning.rstrip("/")
    USERNAME = args.username
    PASSWORD = args.password
    SCANNING_PASSWORD = args.scanning_password or PASSWORD

    if args.scan_detail_id:
        os.environ["SCAN_DETAIL_ID"] = args.scan_detail_id

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    print(f"Capturing screenshots to {output.resolve()}")
    print(f"  Portal:     {PORTAL_URL}")
    print(f"  Deployment: {DEPLOYMENT_URL}")
    print(f"  Scanning:   {SCANNING_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            ignore_https_errors=True,  # Self-signed certs on deployment console
        )

        await capture_portal(context, output)
        await capture_deployment(context, output)
        await capture_scanning(context, output)
        await capture_target_lab(context, output)
        await capture_reports(context, output)

        await context.close()
        await browser.close()

    # Write manifest
    manifest = {
        "captured_at": datetime.now().isoformat(),
        "portal_url": PORTAL_URL,
        "deployment_url": DEPLOYMENT_URL,
        "scanning_url": SCANNING_URL,
        "viewport": VIEWPORT,
        "device_scale": DEVICE_SCALE,
    }
    manifest_path = output / "screenshots_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_path}")
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture screenshots for Talos CleanRoom user guide")
    parser.add_argument("--portal", default=PORTAL_URL, help="Portal URL")
    parser.add_argument("--deployment", default=DEPLOYMENT_URL, help="Deployment Console URL")
    parser.add_argument("--scanning", default=SCANNING_URL, help="Scanning Console URL")
    parser.add_argument("--output", default="../docs/img", help="Output directory for screenshots")
    parser.add_argument("--username", default=USERNAME, help="Login username")
    parser.add_argument("--password", default=PASSWORD, help="Login password for portal and deployment")
    parser.add_argument("--scanning-password", default=None, help="Login password for scanning console (if different)")
    parser.add_argument("--scan-detail-id", default=None, help="Specific scan ID for the scan detail screenshot (e.g. 97a676ca)")
    args = parser.parse_args()

    asyncio.run(main(args))
