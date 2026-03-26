"""Capture the 2 remaining IOC scan screenshots using mocked data."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

SCANNING_URL = "https://scan.knowledgeondemand.net"
USERNAME = "admin"
SCANNING_PASSWORD = "wGOAUYX2P8SLbPyD"
VIEWPORT = {"width": 1280, "height": 800}
OUTPUT = Path("../docs/img")


async def login_and_set_token(page, url, pw):
    resp = await page.request.post(
        f"{url}/api/auth/login",
        data=json.dumps({"username": USERNAME, "password": pw}),
        headers={"Content-Type": "application/json"},
    )
    data = await resp.json()
    token = data["access_token"]
    await page.goto(url, wait_until="networkidle")
    await page.evaluate(f"localStorage.setItem('access_token', '{token}')")


MOCK_LOGS = [
    {"level": "INFO", "message": "Mounting target via SSH: 10.83.3.15:/var",
     "timestamp": "2025-01-01T12:00:05"},
    {"level": "INFO", "message": "Mount successful, starting LOKI-RS scan...",
     "timestamp": "2025-01-01T12:00:15"},
    {"level": "INFO", "message": "Scanning /scan/var/log (1247 files)...",
     "timestamp": "2025-01-01T12:00:30"},
    {"level": "INFO", "message": "Scanning /scan/var/www (832 files)...",
     "timestamp": "2025-01-01T12:01:00"},
]

IOC_RUNNING = {
    "id": "ioc-001", "target_host": "10.83.3.15",
    "mount_type": "ssh", "status": "running",
    "phase": "scanning",
    "phases": [
        {"name": "prepare", "status": "completed"},
        {"name": "mount", "status": "completed"},
        {"name": "scan", "status": "running"},
        {"name": "cleanup", "status": "pending"},
    ],
    "started_at": "2025-01-01T12:00:00", "completed_at": None,
    "findings": [], "alerts_count": 0, "warnings_count": 0, "notices_count": 0,
}

IOC_COMPLETED = {
    "id": "ioc-001", "target_host": "10.83.3.15",
    "mount_type": "ssh", "status": "completed",
    "phase": "cleanup",
    "phases": [
        {"name": "prepare", "status": "completed"},
        {"name": "mount", "status": "completed"},
        {"name": "scan", "status": "completed"},
        {"name": "cleanup", "status": "completed"},
    ],
    "started_at": "2025-01-01T12:00:00", "completed_at": "2025-01-01T12:03:00",
    "findings": [
        {"severity": "alert", "score": 95, "file_path": "/var/tmp/.hidden/nc.exe",
         "rule": "HKTL_Netcat", "description": "Netcat - known hacking tool",
         "md5": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
         "sha256": "abc123def456abc123def456abc123def456abc123def456abc123def456abcd",
         "matched_strings": ["cmd.exe", "/bin/sh"], "tags": ["hacktool", "netcat"]},
        {"severity": "alert", "score": 88, "file_path": "/var/www/html/uploads/shell.php",
         "rule": "WEBSHELL_PHP_Generic", "description": "PHP webshell detected",
         "md5": "f1e2d3c4b5a6f1e2d3c4b5a6f1e2d3c4",
         "sha256": "def456abc123def456abc123def456abc123def456abc123def456abc123defg",
         "matched_strings": ["eval(", "base64_decode("], "tags": ["webshell", "php"]},
        {"severity": "warning", "score": 65, "file_path": "/var/log/auth.log.bak",
         "rule": "SUSP_LOG_Deletion", "description": "Suspicious log backup",
         "md5": "1234567890abcdef1234567890abcdef",
         "sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
         "matched_strings": [], "tags": ["suspicious"]},
        {"severity": "notice", "score": 40, "file_path": "/usr/local/bin/nmap",
         "rule": "TOOL_Nmap", "description": "Network scanning tool detected",
         "md5": "abcdef1234567890abcdef1234567890",
         "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
         "matched_strings": [], "tags": ["tool", "scanner"]},
    ],
    "alerts_count": 2, "warnings_count": 1, "notices_count": 1,
}


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT, device_scale_factor=2, ignore_https_errors=True)

        # --- IOC Running ---
        print("Capturing IOC running state...")
        page = await context.new_page()
        await page.route("**/api/ioc-scan/status", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(IOC_RUNNING)))
        await page.route("**/api/ioc-scan/logs**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(MOCK_LOGS)))
        await page.route("**/api/ioc-scan/history**", lambda r: r.fulfill(
            status=200, content_type="application/json", body="[]"))
        await page.route("**/ws/**", lambda r: r.abort())

        await login_and_set_token(page, SCANNING_URL, SCANNING_PASSWORD)
        await page.goto(f"{SCANNING_URL}/ioc-scan", wait_until="networkidle")
        try:
            await page.wait_for_function(
                "typeof Alpine !== 'undefined'", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        fp = OUTPUT / "scanning" / "scanning-ioc-running.jpg"
        fp.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(fp), type="jpeg", quality=85, full_page=True)
        print(f"  [OK] scanning-ioc-running.jpg")
        await page.close()

        # --- IOC Findings ---
        print("Capturing IOC findings state...")
        page = await context.new_page()
        await page.route("**/api/ioc-scan/status", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(IOC_COMPLETED)))
        await page.route("**/api/ioc-scan/logs**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(MOCK_LOGS)))
        await page.route("**/api/ioc-scan/history**", lambda r: r.fulfill(
            status=200, content_type="application/json", body="[]"))
        await page.route("**/ws/**", lambda r: r.abort())

        await login_and_set_token(page, SCANNING_URL, SCANNING_PASSWORD)
        await page.goto(f"{SCANNING_URL}/ioc-scan", wait_until="networkidle")
        try:
            await page.wait_for_function(
                "typeof Alpine !== 'undefined'", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        fp = OUTPUT / "scanning" / "scanning-ioc-findings.jpg"
        await page.screenshot(path=str(fp), type="jpeg", quality=85, full_page=True)
        print(f"  [OK] scanning-ioc-findings.jpg")
        await page.close()

        await context.close()
        await browser.close()

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
