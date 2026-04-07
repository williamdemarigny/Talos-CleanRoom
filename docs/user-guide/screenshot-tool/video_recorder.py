"""
Talos CleanRoom — Video Recording Tool

Records walkthrough videos of the three web apps using Playwright.
Outputs WebM files that can be converted to MP4 with FFmpeg.

Usage:
    python video_recorder.py --scanning-password "yourpassword"

Post-processing (requires FFmpeg):
    ffmpeg -i video.webm -c:v libx264 -crf 23 -preset medium -c:a aac output.mp4
    ffmpeg -i output.mp4 -vf subtitles=subs.srt output_subtitled.mp4
    ffmpeg -i output.mp4 -filter:v "setpts=0.25*PTS" output_fast.mp4

Prerequisites:
    pip install -r requirements.txt
    python -m playwright install chromium
"""

import argparse
import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Page

PORTAL_URL = "https://cleanroom.knowledgeondemand.net"
DEPLOYMENT_URL = "http://10.83.3.190:8000"
SCANNING_URL = "https://scan.knowledgeondemand.net"
USERNAME = "admin"
PASSWORD = "admin"
SCANNING_PASSWORD = "admin"
VIEWPORT = {"width": 1280, "height": 800}


class SubtitleGenerator:
    """Generates SRT subtitle files from timestamped actions."""

    def __init__(self):
        self.entries = []
        self.start_time = None

    def start(self):
        self.start_time = datetime.now(timezone.utc)

    def add(self, text: str):
        if self.start_time is None:
            self.start()
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        self.entries.append((elapsed, text))

    def save(self, path: Path):
        lines = []
        for i, (timestamp, text) in enumerate(self.entries, 1):
            start = self._fmt(timestamp)
            end = self._fmt(timestamp + 3.0)
            lines.extend([str(i), f"{start} --> {end}", text, ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Subtitles saved: {path.name}")

    @staticmethod
    def _fmt(s: float) -> str:
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        ms = int((s % 1) * 1000)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


async def api_login(page: Page, base_url: str, pw: str) -> bool:
    """Log in via API and set localStorage token."""
    try:
        resp = await page.request.post(
            f"{base_url}/api/auth/login",
            data=json.dumps({"username": USERNAME, "password": pw}),
            headers={"Content-Type": "application/json"},
        )
        if resp.status == 200:
            data = await resp.json()
            await page.goto(base_url, wait_until="networkidle")
            await page.evaluate(
                f"localStorage.setItem('access_token', '{data['access_token']}')"
            )
            return True
    except Exception:
        pass
    print(f"  [WARN] API login failed for {base_url}")
    return False


async def record_getting_started(output: Path) -> Path:
    """Video 1: Portal login -> landing -> credentials -> back (~2 min)."""
    print("\n=== Recording: Video 1 — Getting Started ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            record_video_dir=str(output / "raw"),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()
        subs.start()

        # 1. Login page
        subs.add("Open the Portal at cleanroom.knowledgeondemand.net")
        await page.goto(f"{PORTAL_URL}/login", wait_until="networkidle")
        await page.wait_for_timeout(2500)

        # 2. Fill credentials
        subs.add("Enter username 'admin' and password, then click Sign In")
        await page.fill("input[type='text']", USERNAME)
        await page.wait_for_timeout(500)
        await page.fill("input[type='password']", PASSWORD)
        await page.wait_for_timeout(800)
        await page.click("button[type=submit]")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2500)

        # 3. Landing page
        subs.add("The Portal shows two cards: Deployment Console and Scanning Console")
        await page.wait_for_timeout(3500)

        # 4. Credentials page
        subs.add("Click 'Credentials' to view service passwords")
        try:
            creds_link = page.locator("text=Credentials").first
            if await creds_link.is_visible(timeout=2000):
                await creds_link.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3500)

                subs.add("Each service shows its URL, username, and password")
                await page.wait_for_timeout(3000)

                # Reveal a password
                subs.add("Click the eye icon to reveal a password")
                try:
                    eye_btn = page.locator("button[title='Toggle visibility'], button:has-text('👁')").first
                    if await eye_btn.is_visible(timeout=2000):
                        await eye_btn.click()
                        await page.wait_for_timeout(2500)
                except Exception:
                    pass
        except Exception:
            pass

        # 5. Back to portal
        subs.add("Navigate back to the Portal landing page")
        await page.goto(PORTAL_URL, wait_until="networkidle")
        await page.wait_for_timeout(2500)

        # 6. Click deployment card (show SSO)
        subs.add("Click a card to navigate with automatic single sign-on")
        await page.wait_for_timeout(2000)

        try:
            deploy_card = page.locator("button:has-text('Deployment Console')").first
            if await deploy_card.is_visible(timeout=2000):
                await deploy_card.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3000)

                subs.add("You are automatically logged in to the Deployment Console")
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 7. Show deployment dashboard briefly
        subs.add("The Dashboard shows deployment status and service credentials")
        await page.wait_for_timeout(3000)

        # End
        subs.add("That's the basics — you're ready to use Talos CleanRoom!")
        await page.wait_for_timeout(2000)

        video_path = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "01-getting-started.srt")
    print(f"  Video recorded: {video_path}")
    return Path(video_path)


async def record_reports_tour(output: Path) -> Path:
    """Video 5: Reports dashboard -> detail -> hosts -> vulns -> compare -> audit (~3 min)."""
    print("\n=== Recording: Video 5 — Reports Tour ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            record_video_dir=str(output / "raw"),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()

        await api_login(page, SCANNING_URL, SCANNING_PASSWORD)
        subs.start()

        # 1. Reports dashboard
        subs.add("The Reports dashboard shows scan statistics and recent scans")
        await page.goto(f"{SCANNING_URL}/reports", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        # 2. Scan detail
        subs.add("Click 'View Details' to see a full scan breakdown")
        try:
            detail_link = page.locator("text=View Details").first
            if await detail_link.is_visible(timeout=3000):
                await detail_link.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3500)

                subs.add("The scan detail shows hosts, services, and vulnerabilities")
                await page.wait_for_timeout(3000)
        except Exception:
            subs.add("Navigate to a scan to see hosts, services, and vulnerabilities")
            await page.wait_for_timeout(2000)

        # 3. Hosts
        subs.add("The Hosts page shows all discovered IP addresses")
        await page.goto(f"{SCANNING_URL}/reports/hosts", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        # 4. Vulnerabilities
        subs.add("Filter vulnerabilities by severity, remediation status, and CVSS score")
        await page.goto(f"{SCANNING_URL}/reports/vulns", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        # Scroll down a bit to show data
        await page.evaluate("window.scrollBy(0, 300)")
        await page.wait_for_timeout(2500)

        subs.add("Each vulnerability shows its CVSS score and EPSS exploit probability")
        await page.wait_for_timeout(3000)

        # 5. Compare
        subs.add("Compare two scans to track remediation progress over time")
        await page.goto(f"{SCANNING_URL}/reports/compare", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        subs.add("Select two scans to see new, resolved, and common findings")
        await page.wait_for_timeout(3000)

        # 6. Audit
        subs.add("The Audit Log records all user actions for accountability")
        await page.goto(f"{SCANNING_URL}/reports/audit", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        subs.add("Every scan start, export, and enrichment trigger is logged")
        await page.wait_for_timeout(2500)

        video_path = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "05-reports-tour.srt")
    print(f"  Video recorded: {video_path}")
    return Path(video_path)


async def record_deployment(output: Path) -> Path:
    """Video 2: Deployment walkthrough — start deployment, watch progress, completion (~30-60 min raw, condensed in post).

    Must be run DURING a live deployment or just before starting one.
    The video captures: idle state -> click Start -> steps progressing -> completion banner.
    Post-process with FFmpeg to speed up the long middle section.
    """
    print("\n=== Recording: Video 2 — Deployment Walkthrough ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            record_video_dir=str(output / "raw"),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()

        await api_login(page, DEPLOYMENT_URL, PASSWORD)
        subs.start()

        # 1. Dashboard overview
        subs.add("Open the Deployment Console dashboard")
        await page.goto(DEPLOYMENT_URL, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # 2. Navigate to deployment page
        subs.add("Navigate to the Deployment tab")
        await page.goto(f"{DEPLOYMENT_URL}/deployment", wait_until="networkidle")
        await page.wait_for_timeout(2500)

        # 3. Click Start Deployment
        subs.add("Click Start Deployment to begin the 23-step process")
        try:
            start_btn = page.locator("button:has-text('Start Deployment')").first
            if await start_btn.is_visible(timeout=5000):
                await start_btn.click()
                await page.wait_for_timeout(2000)

                # 4. Confirm if prompted
                try:
                    confirm_btn = page.locator("button:has-text('Confirm'), button:has-text('Yes')").first
                    if await confirm_btn.is_visible(timeout=3000):
                        subs.add("Confirm the deployment")
                        await confirm_btn.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass
            else:
                subs.add("Deployment is already in progress — monitoring")
        except Exception:
            subs.add("Deployment is already in progress — monitoring")

        # 5. Watch progress — poll until deployment finishes or timeout
        subs.add("The deployment runs 23 automated steps")
        max_poll_minutes = 75  # Safety timeout
        poll_interval = 15  # seconds
        total_polls = (max_poll_minutes * 60) // poll_interval
        last_step = -1

        for i in range(total_polls):
            await page.wait_for_timeout(poll_interval * 1000)

            # Check current status via page content
            try:
                status_text = await page.evaluate("""() => {
                    const el = document.querySelector('[x-data]');
                    if (el) {
                        const data = Alpine.$data(el);
                        return JSON.stringify({status: data.status, step: data.currentStep});
                    }
                    return '{}';
                }""")
                import json as _json
                status = _json.loads(status_text)

                current_step = status.get("step", -1)
                if current_step != last_step and current_step >= 0:
                    subs.add(f"Step {current_step + 1} of 23 in progress")
                    last_step = current_step

                if status.get("status") in ("completed", "failed"):
                    break
            except Exception:
                pass

        # 6. Final state
        await page.wait_for_timeout(3000)
        try:
            status_text = await page.evaluate("""() => {
                const el = document.querySelector('[x-data]');
                if (el) { return Alpine.$data(el).status; }
                return '';
            }""")
            if status_text == "completed":
                subs.add("Deployment completed successfully!")
            elif status_text == "failed":
                subs.add("Deployment encountered an error — see Recovery guide")
            else:
                subs.add("Deployment is still running — video recording ended")
        except Exception:
            subs.add("Deployment recording complete")

        await page.wait_for_timeout(3000)

        video_path = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "02-deployment.srt")
    print(f"  Video recorded: {video_path}")
    print("  NOTE: This video is likely very long. Speed up with:")
    print("    ffmpeg -i raw/video.webm -filter:v \"setpts=0.1*PTS\" -an 02-deployment-fast.mp4")
    return Path(video_path)


async def record_vuln_scan(output: Path) -> Path:
    """Video 3: Target Lab deploy + vulnerability scan walkthrough.

    Flow: Target Lab catalog → deploy a target → wait for running →
    click Scan (pre-fills target) → run Quick scan → completion.
    """
    print("\n=== Recording: Video 3 — Target Lab + Vulnerability Scan ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            record_video_dir=str(output / "raw"),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()

        await api_login(page, SCANNING_URL, SCANNING_PASSWORD)
        subs.start()

        # ── Part 1: Target Lab ──────────────────────────────────

        # 1. Navigate to Target Lab
        subs.add("Open the Target Lab to deploy a vulnerable test environment")
        await page.goto(f"{SCANNING_URL}/target-lab", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # 2. Browse the catalog
        subs.add("The catalog shows Vulhub environments with CVE info and difficulty")
        await page.wait_for_timeout(3000)

        # 3. Deploy the first available environment
        subs.add("Click Deploy on an environment to create it in the cluster")
        target_deployed = False
        try:
            deploy_btn = page.locator("button:has-text('Deploy')").first
            if await deploy_btn.is_visible(timeout=5000):
                await deploy_btn.click()
                await page.wait_for_timeout(2000)
                target_deployed = True

                subs.add("The target is being created — watch the status change")
                await page.wait_for_timeout(2000)

                # 4. Scroll down to show Active Targets table
                await page.evaluate("window.scrollBy(0, 400)")
                await page.wait_for_timeout(2000)

                # 5. Expand deploy logs if visible
                try:
                    logs_btn = page.locator("button:has-text('Logs')").first
                    if await logs_btn.is_visible(timeout=3000):
                        subs.add("Click Logs to watch the deployment progress")
                        await logs_btn.click()
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass

                # 6. Wait for target to reach "running" status (poll up to 3 min)
                subs.add("Waiting for the target to become ready...")
                for i in range(18):  # 18 * 10s = 3 min
                    await page.wait_for_timeout(10000)
                    try:
                        has_running = await page.evaluate("""() => {
                            const el = document.querySelector('[x-data]');
                            if (el) {
                                const data = Alpine.$data(el);
                                return (data.targets || []).some(t => t.status === 'running');
                            }
                            return false;
                        }""")
                        if has_running:
                            break
                    except Exception:
                        pass
                    # Refresh the page periodically to pick up status changes
                    if i % 3 == 2:
                        await page.goto(f"{SCANNING_URL}/target-lab", wait_until="networkidle")
                        await page.wait_for_timeout(1000)
                        await page.evaluate("window.scrollBy(0, 400)")

                await page.wait_for_timeout(2000)

                # 7. Click Scan on the running target
                subs.add("Target is running — click Scan to start scanning it")
                try:
                    scan_btn = page.locator("button:has-text('Scan')").first
                    if await scan_btn.is_visible(timeout=5000):
                        await scan_btn.click()
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(2500)

                        subs.add("The Scan page opens with the target and recommended profile pre-filled")
                        await page.wait_for_timeout(2500)
                except Exception:
                    pass
        except Exception:
            pass

        # ── Part 2: Vulnerability Scan ──────────────────────────

        # If Target Lab wasn't available, fall back to manual scan setup
        if not target_deployed:
            subs.add("Open the Scan page in the Scanning Console")
            await page.goto(f"{SCANNING_URL}/scan", wait_until="networkidle")
            await page.wait_for_timeout(2500)

            subs.add("Enter a target IP address or CIDR range")
            try:
                target_input = page.locator(
                    "input[placeholder*='target'], input[placeholder*='IP'], #target"
                ).first
                if await target_input.is_visible(timeout=3000):
                    await target_input.fill("10.83.3.10")
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            subs.add("Select the scanning tools: Nmap and OpenVAS")
            try:
                for tool_label in ["Nmap", "OpenVAS"]:
                    checkbox = page.locator(f"text={tool_label}").first
                    if await checkbox.is_visible(timeout=2000):
                        await checkbox.click()
                        await page.wait_for_timeout(500)
            except Exception:
                pass

            subs.add("Choose the Quick profile for a fast initial scan")
            try:
                quick_btn = page.locator("button:has-text('Quick')").first
                if await quick_btn.is_visible(timeout=2000):
                    await quick_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            await page.wait_for_timeout(1500)

        # 8. Start scan (target may already be pre-filled from Target Lab)
        subs.add("Click Start Scan to begin")
        try:
            start_btn = page.locator("button:has-text('Start Scan')").first
            if await start_btn.is_visible(timeout=3000):
                await start_btn.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 9. Watch progress — poll for up to 10 minutes
        subs.add("The scan shows real-time progress for each tool")
        max_polls = 40  # 40 * 15s = 10 min
        for i in range(max_polls):
            await page.wait_for_timeout(15000)

            try:
                status_text = await page.evaluate("""() => {
                    const el = document.querySelector('[x-data]');
                    if (el) { return Alpine.$data(el).status || ''; }
                    return '';
                }""")
                if status_text in ("completed", "failed"):
                    break
            except Exception:
                pass

            if i == 2:
                subs.add("Nmap discovers open ports and running services")
            elif i == 6:
                subs.add("OpenVAS performs deep vulnerability testing")

        # 10. Completion
        await page.wait_for_timeout(3000)
        subs.add("Scan complete — results are shown with findings per tool")
        await page.wait_for_timeout(2500)

        # 11. Scroll to show enrichment
        subs.add("Enrichment adds CVSS scores and EPSS exploit probability data")
        await page.evaluate("window.scrollBy(0, 300)")
        await page.wait_for_timeout(3000)

        subs.add("Click 'Reports' to view detailed findings")
        await page.wait_for_timeout(2000)

        video_path = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "03-vuln-scan.srt")
    print(f"  Video recorded: {video_path}")
    return Path(video_path)


async def record_ioc_scan(output: Path) -> Path:
    """Video 4: IOC scan walkthrough — configure and run an IOC scan (~2-3 min)."""
    print("\n=== Recording: Video 4 — IOC Scan Walkthrough ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            record_video_dir=str(output / "raw"),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()

        await api_login(page, SCANNING_URL, SCANNING_PASSWORD)
        subs.start()

        # 1. Navigate to IOC Scan page
        subs.add("Open the IOC Scan page in the Scanning Console")
        await page.goto(f"{SCANNING_URL}/ioc-scan", wait_until="networkidle")
        await page.wait_for_timeout(2500)

        # 2. Fill in target host
        subs.add("Enter the target host IP address")
        try:
            host_input = page.locator("input[placeholder*='host'], input[placeholder*='IP'], #target-host").first
            if await host_input.is_visible(timeout=3000):
                await host_input.fill("10.83.3.15")
                await page.wait_for_timeout(800)
        except Exception:
            pass

        # 3. SSH is default, fill credentials
        subs.add("Enter SSH credentials for the target server")
        try:
            user_input = page.locator("#ssh-username, input[placeholder*='username']").first
            if await user_input.is_visible(timeout=2000):
                await user_input.fill("root")
                await page.wait_for_timeout(500)

            pass_input = page.locator("#ssh-password, input[placeholder*='password']").first
            if await pass_input.is_visible(timeout=2000):
                await pass_input.fill("password")
                await page.wait_for_timeout(500)

            path_input = page.locator("#remote-path, input[placeholder*='path']").first
            if await path_input.is_visible(timeout=2000):
                await path_input.fill("/var")
                await page.wait_for_timeout(500)
        except Exception:
            pass

        await page.wait_for_timeout(1500)

        # 4. Start scan
        subs.add("Click Start IOC Scan")
        try:
            start_btn = page.locator("button:has-text('Start IOC Scan')").first
            if await start_btn.is_visible(timeout=3000):
                await start_btn.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 5. Watch phases
        subs.add("The scan progresses through four phases: Prepare, Mount, Scan, Cleanup")
        max_polls = 24  # 24 * 15s = 6 min
        for i in range(max_polls):
            await page.wait_for_timeout(15000)

            try:
                status_text = await page.evaluate("""() => {
                    const el = document.querySelector('[x-data]');
                    if (el) { return Alpine.$data(el).status || ''; }
                    return '';
                }""")
                if status_text in ("completed", "failed"):
                    break
            except Exception:
                pass

            if i == 1:
                subs.add("LOKI-RS scans files against YARA rules and known threat hashes")

        # 6. Completion and findings
        await page.wait_for_timeout(3000)
        subs.add("Scan complete — findings are categorized by severity")
        await page.wait_for_timeout(2500)

        # Scroll to show findings table
        subs.add("Alerts (red) require immediate investigation")
        await page.evaluate("window.scrollBy(0, 400)")
        await page.wait_for_timeout(3000)

        subs.add("Click any finding to see file hashes, matched rules, and tags")
        await page.wait_for_timeout(2500)

        video_path = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "04-ioc-scan.srt")
    print(f"  Video recorded: {video_path}")
    return Path(video_path)


def convert_to_mp4(webm_path: Path, mp4_path: Path, srt_path: Path = None) -> bool:
    """Convert WebM to MP4, optionally burning in subtitles."""
    ffmpeg = "ffmpeg"

    # Step 1: Convert WebM -> MP4
    cmd = [ffmpeg, "-y", "-i", str(webm_path),
           "-c:v", "libx264", "-crf", "23", "-preset", "medium",
           "-c:a", "aac", str(mp4_path)]
    print(f"  Converting {webm_path.name} -> {mp4_path.name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] FFmpeg conversion failed: {result.stderr[-200:]}")
        return False

    # Step 2: Burn subtitles if provided
    if srt_path and srt_path.exists():
        subtitled = mp4_path.with_stem(mp4_path.stem + "_subtitled")
        cmd = [ffmpeg, "-y", "-i", str(mp4_path),
               "-vf", f"subtitles={str(srt_path)}", str(subtitled)]
        print(f"  Burning subtitles -> {subtitled.name}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [WARN] Subtitle burn failed (video still saved without subs)")
        else:
            print(f"  [OK] {subtitled.name}")

    print(f"  [OK] {mp4_path.name}")
    return True


async def main(args: argparse.Namespace) -> None:
    global PORTAL_URL, DEPLOYMENT_URL, SCANNING_URL, USERNAME, PASSWORD, SCANNING_PASSWORD
    PORTAL_URL = args.portal.rstrip("/")
    DEPLOYMENT_URL = args.deployment.rstrip("/")
    SCANNING_URL = args.scanning.rstrip("/")
    USERNAME = args.username
    PASSWORD = args.password
    SCANNING_PASSWORD = args.scanning_password or PASSWORD

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)

    print(f"Recording videos to {output.resolve()}")

    videos_to_record = args.videos.split(",") if args.videos else ["1", "5"]

    recorded = {}

    for vid in videos_to_record:
        vid = vid.strip()
        if vid == "1":
            recorded["1"] = await record_getting_started(output)
        elif vid == "2":
            recorded["2"] = await record_deployment(output)
        elif vid == "3":
            recorded["3"] = await record_vuln_scan(output)
        elif vid == "4":
            recorded["4"] = await record_ioc_scan(output)
        elif vid == "5":
            recorded["5"] = await record_reports_tour(output)
        elif vid == "all":
            recorded["1"] = await record_getting_started(output)
            recorded["5"] = await record_reports_tour(output)
            print("\n" + "=" * 60)
            print("Videos 2-4 require live operations.")
            print("Record them individually with --videos 2, --videos 3, --videos 4")
            print("=" * 60)
            break
        else:
            print(f"  [WARN] Unknown video number: {vid}")

    # Convert to MP4 if FFmpeg is available
    print("\n=== Post-Processing ===")
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        has_ffmpeg = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_ffmpeg = False

    video_names = {
        "1": "01-getting-started",
        "2": "02-deployment",
        "3": "03-vuln-scan",
        "4": "04-ioc-scan",
        "5": "05-reports-tour",
    }

    if has_ffmpeg:
        for vid_num, webm_path in recorded.items():
            name = video_names.get(vid_num, f"video-{vid_num}")
            convert_to_mp4(webm_path, output / f"{name}.mp4",
                            output / f"{name}.srt")
    else:
        print("  FFmpeg not found — skipping MP4 conversion.")
        print("  Raw WebM files are in the 'raw/' subdirectory.")
        print("  Convert manually: ffmpeg -i video.webm -c:v libx264 -crf 23 output.mp4")

    if "2" in recorded:
        print("\n  NOTE: Video 2 (Deployment) is likely very long.")
        print("  Speed up: ffmpeg -i 02-deployment.mp4 -filter:v \"setpts=0.1*PTS\" -an 02-deployment-fast.mp4")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record walkthrough videos")
    parser.add_argument("--portal", default=PORTAL_URL)
    parser.add_argument("--deployment", default=DEPLOYMENT_URL)
    parser.add_argument("--scanning", default=SCANNING_URL)
    parser.add_argument("--output", default="./videos")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--scanning-password", default=None)
    parser.add_argument("--videos", default=None,
                        help="Comma-separated video numbers to record (1-5 or 'all'). "
                             "Default: 1,5. Videos 2-4 require live operations.")
    args = parser.parse_args()
    asyncio.run(main(args))
