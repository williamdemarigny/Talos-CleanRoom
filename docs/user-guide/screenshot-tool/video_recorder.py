"""
Talos CleanRoom — Video Recording Tool

Records walkthrough videos of the three web apps using Playwright.
Outputs WebM files that can be converted to MP4 with FFmpeg.

Usage:
    python video_recorder.py --portal https://cleanroom.knowledgeondemand.net \
                             --deployment https://10.83.3.190:8000 \
                             --scanning https://scan.knowledgeondemand.net \
                             --output ./videos

Post-processing (requires FFmpeg):
    # Convert WebM to MP4
    ffmpeg -i video.webm -c:v libx264 -crf 23 -preset medium -c:a aac output.mp4

    # Burn in subtitles
    ffmpeg -i output.mp4 -vf subtitles=subs.srt output_subtitled.mp4

    # Speed up slow sections (4x)
    ffmpeg -i output.mp4 -filter:v "setpts=0.25*PTS" output_fast.mp4

Prerequisites:
    pip install -r requirements.txt
    python -m playwright install chromium
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

# Default URLs
PORTAL_URL = "https://cleanroom.knowledgeondemand.net"
DEPLOYMENT_URL = "http://10.83.3.190:8000"
SCANNING_URL = "https://scan.knowledgeondemand.net"

USERNAME = "admin"
PASSWORD = "admin"

VIEWPORT = {"width": 1280, "height": 800}


class SubtitleGenerator:
    """Generates SRT subtitle files from timestamped actions."""

    def __init__(self):
        self.entries = []
        self.start_time = None

    def start(self):
        self.start_time = datetime.utcnow()

    def add(self, text: str):
        if self.start_time is None:
            self.start()
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        self.entries.append((elapsed, text))

    def save(self, path: Path):
        """Write SRT subtitle file."""
        lines = []
        for i, (timestamp, text) in enumerate(self.entries, 1):
            # Show each subtitle for 3 seconds
            start = self._format_time(timestamp)
            end = self._format_time(timestamp + 3.0)
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Subtitles: {path}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def login(page: Page, base_url: str) -> None:
    """Log in to an app."""
    response = await page.request.post(
        f"{base_url}/api/auth/login",
        data=json.dumps({"username": USERNAME, "password": PASSWORD}),
        headers={"Content-Type": "application/json"},
    )
    data = await response.json()
    token = data.get("access_token", "")
    await page.goto(base_url, wait_until="networkidle")
    await page.evaluate(f"localStorage.setItem('access_token', '{token}')")


async def record_getting_started(context_args: dict, output: Path) -> None:
    """Record Video 1: Getting Started walkthrough (~2 min)."""
    print("\n=== Recording: Getting Started ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            **context_args,
            record_video_dir=str(output),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()
        subs.start()

        # Login page
        subs.add("Navigate to the Portal login page")
        await page.goto(f"{PORTAL_URL}/login", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Fill credentials and login
        subs.add("Enter username and password, then click Sign In")
        await page.fill("#username", USERNAME)
        await page.fill("#password", PASSWORD)
        await page.wait_for_timeout(1000)
        await page.click("button[type=submit]")
        await page.wait_for_network_idle()
        await page.wait_for_timeout(2000)

        # Landing page
        subs.add("The Portal landing page shows two app cards")
        await page.wait_for_timeout(3000)

        # Credentials
        subs.add("Click Credentials to view service passwords")
        try:
            await page.click("text=Credentials")
            await page.wait_for_network_idle()
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Back to portal
        subs.add("Return to the Portal landing page")
        await page.goto(PORTAL_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        subs.add("Click a card to navigate with single sign-on")
        await page.wait_for_timeout(3000)

        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "01-getting-started.srt")
    print("  Video saved to output directory")


async def record_reports_tour(context_args: dict, output: Path) -> None:
    """Record Video 5: Reports Tour walkthrough (~3 min)."""
    print("\n=== Recording: Reports Tour ===")
    subs = SubtitleGenerator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            **context_args,
            record_video_dir=str(output),
            record_video_size=VIEWPORT,
        )
        page = await context.new_page()

        await login(page, SCANNING_URL)
        subs.start()

        # Reports dashboard
        subs.add("The Reports dashboard shows scan statistics")
        await page.goto(f"{SCANNING_URL}/reports", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Scan detail
        subs.add("Click View Details to drill into a specific scan")
        try:
            await page.click("text=View Details")
            await page.wait_for_network_idle()
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Hosts
        subs.add("Browse discovered hosts across all scans")
        await page.goto(f"{SCANNING_URL}/reports/hosts", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Vulnerabilities
        subs.add("Filter vulnerabilities by severity, status, and scores")
        await page.goto(f"{SCANNING_URL}/reports/vulns", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Compare
        subs.add("Compare two scans to track remediation progress")
        await page.goto(f"{SCANNING_URL}/reports/compare", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Audit
        subs.add("The Audit Log records all user actions")
        await page.goto(f"{SCANNING_URL}/reports/audit", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        await page.close()
        await context.close()
        await browser.close()

    subs.save(output / "05-reports-tour.srt")
    print("  Video saved to output directory")


async def main(args: argparse.Namespace) -> None:
    global PORTAL_URL, DEPLOYMENT_URL, SCANNING_URL
    PORTAL_URL = args.portal.rstrip("/")
    DEPLOYMENT_URL = args.deployment.rstrip("/")
    SCANNING_URL = args.scanning.rstrip("/")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    context_args = {
        "viewport": VIEWPORT,
        "ignore_https_errors": True,
    }

    print(f"Recording videos to {output.resolve()}")

    # Videos 1 and 5 can be recorded against current state
    await record_getting_started(context_args, output)
    await record_reports_tour(context_args, output)

    print("\n" + "=" * 60)
    print("Videos 2-4 require live operations:")
    print("  Video 2 (Deployment): Run during a fresh deployment")
    print("  Video 3 (Vuln Scan):  Run during a Quick scan")
    print("  Video 4 (IOC Scan):   Run during an IOC scan")
    print()
    print("Post-processing commands:")
    print("  ffmpeg -i video.webm -c:v libx264 -crf 23 -preset medium output.mp4")
    print("  ffmpeg -i output.mp4 -vf subtitles=subs.srt output_subtitled.mp4")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record walkthrough videos")
    parser.add_argument("--portal", default=PORTAL_URL)
    parser.add_argument("--deployment", default=DEPLOYMENT_URL)
    parser.add_argument("--scanning", default=SCANNING_URL)
    parser.add_argument("--output", default="./videos")
    args = parser.parse_args()

    asyncio.run(main(args))
