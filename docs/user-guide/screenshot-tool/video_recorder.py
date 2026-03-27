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

    # Record Videos 1 and 5
    v1_webm = await record_getting_started(output)
    v5_webm = await record_reports_tour(output)

    # Convert to MP4 if FFmpeg is available
    print("\n=== Post-Processing ===")
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        has_ffmpeg = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        has_ffmpeg = False

    if has_ffmpeg:
        convert_to_mp4(v1_webm, output / "01-getting-started.mp4",
                        output / "01-getting-started.srt")
        convert_to_mp4(v5_webm, output / "05-reports-tour.mp4",
                        output / "05-reports-tour.srt")
    else:
        print("  FFmpeg not found — skipping MP4 conversion.")
        print("  Raw WebM files are in the 'raw/' subdirectory.")
        print("  Convert manually: ffmpeg -i video.webm -c:v libx264 -crf 23 output.mp4")

    print("\n" + "=" * 60)
    print("Videos 2-4 require live operations:")
    print("  Video 2 (Deployment): Run during a fresh deployment")
    print("  Video 3 (Vuln Scan):  Run during a Quick scan")
    print("  Video 4 (IOC Scan):   Run during an IOC scan")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record walkthrough videos")
    parser.add_argument("--portal", default=PORTAL_URL)
    parser.add_argument("--deployment", default=DEPLOYMENT_URL)
    parser.add_argument("--scanning", default=SCANNING_URL)
    parser.add_argument("--output", default="./videos")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--scanning-password", default=None)
    args = parser.parse_args()
    asyncio.run(main(args))
