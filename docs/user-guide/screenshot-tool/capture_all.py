"""
Talos CleanRoom — Automated End-to-End Capture Orchestrator

Runs all screenshot and video captures in sequence without human interaction.
Designed to run unattended for ~60-100 minutes after kicking off a fresh deployment.

Usage:
    python capture_all.py --ioc-password "password123"
    python capture_all.py --skip-deployment --scanning-password "abc123" --ioc-password "xyz"

Prerequisites:
    pip install -r requirements.txt
    python -m playwright install chromium
    FFmpeg installed (choco install ffmpeg)
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
PORTAL_URL = "https://cleanroom.knowledgeondemand.net"
DEPLOYMENT_URL = "http://10.83.3.190:8000"
SCANNING_URL = "https://scan.knowledgeondemand.net"
USERNAME = "admin"
PASSWORD = "admin"

SCRIPT_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Logging setup — console + file
# ---------------------------------------------------------------------------
def setup_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("capture_all")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    fh = logging.FileHandler(str(log_file), mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# Helper: run a capture sub-script
# ---------------------------------------------------------------------------
def run_script(script: str, args: list, log: logging.Logger, timeout: int = 600) -> bool:
    """Run a Python capture script as a subprocess with real-time output streaming."""
    cmd = [sys.executable, "-u", str(SCRIPT_DIR / script)] + args  # -u = unbuffered
    log.info(f"  Running: {script} {' '.join(a for a in args if 'password' not in a.lower())}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,  # line-buffered
            cwd=str(SCRIPT_DIR),
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
        deadline = time.time() + timeout
        while True:
            line = proc.stdout.readline()
            if line:
                log.info(f"    {line.rstrip()}")
            elif proc.poll() is not None:
                break
            if time.time() > deadline:
                proc.kill()
                proc.wait()
                log.error(f"  {script} timed out after {timeout}s")
                return False
        rc = proc.returncode
        if rc != 0:
            log.error(f"  {script} exited with code {rc}")
            return False
        return True
    except Exception as e:
        log.error(f"  {script} failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Helper: fetch scanning password from deployment API
# ---------------------------------------------------------------------------
def fetch_scanning_password(deployment_url: str, password: str,
                            log: logging.Logger) -> str | None:
    """Log in to deployment console and fetch scanning console password."""
    try:
        # Step 1: Login to get JWT
        login_data = json.dumps({"username": USERNAME, "password": password}).encode()
        req = urllib.request.Request(
            f"{deployment_url}/api/auth/login",
            data=login_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode())["access_token"]

        # Step 2: Fetch credentials
        req = urllib.request.Request(
            f"{deployment_url}/api/deployment/credentials",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            creds = json.loads(resp.read().decode())

        sc_pw = creds.get("credentials", {}).get("scanning_console", {}).get("password")
        if sc_pw:
            log.info(f"  Scanning console password fetched successfully")
            return sc_pw
        log.warning("  No scanning_console password in credentials response")
    except Exception as e:
        log.warning(f"  Failed to fetch scanning password: {e}")
    return None


# ---------------------------------------------------------------------------
# Helper: poll deployment status
# ---------------------------------------------------------------------------
def poll_deployment_status(deployment_url: str, password: str,
                           log: logging.Logger,
                           max_minutes: int = 75, interval: int = 30) -> str:
    """Poll deployment status until completed/failed. Returns final status."""
    total_polls = (max_minutes * 60) // interval

    # Get token first
    try:
        login_data = json.dumps({"username": USERNAME, "password": password}).encode()
        req = urllib.request.Request(
            f"{deployment_url}/api/auth/login",
            data=login_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode())["access_token"]
    except Exception as e:
        log.error(f"  Login failed for status polling: {e}")
        return "unknown"

    status = "unknown"
    for i in range(total_polls):
        time.sleep(interval)
        try:
            req = urllib.request.Request(
                f"{deployment_url}/api/deployment/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                step = data.get("current_step", -1)
                status = data.get("status", "unknown")
                elapsed = (i + 1) * interval // 60
                log.info(f"  [{elapsed}m] Step {step + 1}/26 — {status}")
                if status in ("completed", "failed", "aborted"):
                    return status
        except Exception as e:
            if i == 0:
                log.warning(f"  Status poll failed: {e}")
    return status


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Automated end-to-end screenshot and video capture"
    )
    parser.add_argument("--portal", default=PORTAL_URL)
    parser.add_argument("--deployment", default=DEPLOYMENT_URL)
    parser.add_argument("--scanning", default=SCANNING_URL)
    parser.add_argument("--password", default=PASSWORD,
                        help="Deployment console password (default: admin)")
    parser.add_argument("--scanning-password", default=None,
                        help="Override scanning console password (auto-fetched if omitted)")
    parser.add_argument("--ioc-target", default="10.83.1.113")
    parser.add_argument("--ioc-username", default="administrator")
    parser.add_argument("--ioc-password", required=True,
                        help="IOC scan SMB password (required)")
    parser.add_argument("--ioc-share", default="C$")
    parser.add_argument("--output-img", default=str(SCRIPT_DIR / ".." / "docs" / "img"))
    parser.add_argument("--output-video", default=str(SCRIPT_DIR / ".." / "docs" / "videos"))
    parser.add_argument("--skip-deployment", action="store_true",
                        help="Skip deployment, assume cluster is already deployed")
    parser.add_argument("--scan-tools", default="Nmap,Metasploit",
                        help="Comma-separated scan tools for Video 3 (default: Nmap,Metasploit)")
    args = parser.parse_args()

    # Resolve absolute paths
    img_output = Path(args.output_img).resolve()
    video_output = Path(args.output_video).resolve()
    img_output.mkdir(parents=True, exist_ok=True)
    video_output.mkdir(parents=True, exist_ok=True)
    (video_output / "raw").mkdir(exist_ok=True)

    log_file = SCRIPT_DIR / "capture_all.log"
    log = setup_logging(log_file)

    start_time = time.time()
    results = {}

    log.info("=" * 60)
    log.info("  Talos CleanRoom — Automated Capture Orchestrator")
    log.info("=" * 60)
    log.info(f"  Portal:      {args.portal}")
    log.info(f"  Deployment:  {args.deployment}")
    log.info(f"  Scanning:    {args.scanning}")
    log.info(f"  IOC target:  {args.ioc_target} (SMB, {args.ioc_share})")
    log.info(f"  Scan tools:  {args.scan_tools}")
    log.info(f"  Images:      {img_output}")
    log.info(f"  Videos:      {video_output}")
    log.info(f"  Log:         {log_file}")
    log.info(f"  Skip deploy: {args.skip_deployment}")
    log.info("")

    # ── Pre-flight checks ──────────────────────────────────────
    log.info("Phase 0: Pre-flight checks")
    try:
        from playwright.async_api import async_playwright  # noqa: F401
        log.info("  Playwright: OK")
    except ImportError:
        log.error("  Playwright not installed! Run: pip install playwright && python -m playwright install chromium")
        return

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        log.info("  FFmpeg: OK")
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.warning("  FFmpeg not found — videos will remain as WebM (no MP4 conversion)")

    results["phase0"] = True

    # ── Phase 2: Deployment + Video 2 ──────────────────────────
    if not args.skip_deployment:
        log.info("")
        log.info("Phase 2: Deployment + Video 2 recording")
        try:
            ok = run_script("video_recorder.py", [
                "--videos", "2",
                "--deployment", args.deployment,
                "--password", args.password,
                "--output", str(video_output),
            ], log, timeout=5400)  # 90 min timeout
            results["phase2_video"] = ok
            if not ok:
                log.warning("  Video 2 recording had issues, but continuing...")
        except Exception as e:
            log.error(f"  Phase 2 failed: {e}")
            results["phase2_video"] = False
    else:
        log.info("")
        log.info("Phase 2: SKIPPED (--skip-deployment)")
        results["phase2_video"] = "skipped"

    # ── Phase 3: Fetch scanning password ───────────────────────
    log.info("")
    log.info("Phase 3: Fetching scanning console password")
    scanning_pw = args.scanning_password
    if not scanning_pw:
        scanning_pw = fetch_scanning_password(args.deployment, args.password, log)
    if not scanning_pw:
        scanning_pw = args.password
        log.warning(f"  Falling back to deployment password for scanning console")
    results["phase3_creds"] = scanning_pw != args.password

    # ── Phase 4: Static screenshots ────────────────────────────
    log.info("")
    log.info("Phase 4: Static screenshots (capture.py)")
    results["phase4_screenshots"] = run_script("capture.py", [
        "--portal", args.portal,
        "--deployment", args.deployment,
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--output", str(img_output),
    ], log, timeout=600)

    # ── Phase 5: Mocked screenshots ────────────────────────────
    log.info("")
    log.info("Phase 5: Mocked/transient screenshots")
    r1 = run_script("capture_remaining.py", [
        "--deployment", args.deployment,
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--output", str(img_output),
    ], log, timeout=600)
    r2 = run_script("capture_ioc.py", [
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--output", str(img_output),
    ], log, timeout=120)
    results["phase5_mocked"] = r1 and r2

    # ── Phase 6: Video 1 — Getting Started ─────────────────────
    log.info("")
    log.info("Phase 6: Video 1 — Getting Started")
    results["phase6_video1"] = run_script("video_recorder.py", [
        "--videos", "1",
        "--portal", args.portal,
        "--deployment", args.deployment,
        "--scanning", args.scanning,
        "--password", args.password,
        "--scanning-password", scanning_pw,
        "--output", str(video_output),
    ], log, timeout=300)

    # ── Phase 7: Video 3 — Target Lab + Vuln Scan ─────────────
    log.info("")
    log.info(f"Phase 7: Video 3 — Target Lab + Vulnerability Scan ({args.scan_tools})")
    results["phase7_video3"] = run_script("video_recorder.py", [
        "--videos", "3",
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--scan-tools", args.scan_tools,
        "--output", str(video_output),
    ], log, timeout=1200)  # 20 min

    # ── Phase 8: Video 4 — IOC Scan ───────────────────────────
    log.info("")
    log.info("Phase 8: Video 4 — IOC Scan (SMB)")
    results["phase8_video4"] = run_script("video_recorder.py", [
        "--videos", "4",
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--ioc-target", args.ioc_target,
        "--ioc-username", args.ioc_username,
        "--ioc-password", args.ioc_password,
        "--ioc-mount-type", "smb",
        "--ioc-share", args.ioc_share,
        "--output", str(video_output),
    ], log, timeout=900)  # 15 min

    # ── Phase 9: Video 5 — Reports Tour ───────────────────────
    log.info("")
    log.info("Phase 9: Video 5 — Reports Tour (with scan data)")
    results["phase9_video5"] = run_script("video_recorder.py", [
        "--videos", "5",
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--output", str(video_output),
    ], log, timeout=300)

    # ── Phase 10: Re-capture reports screenshots ──────────────
    log.info("")
    log.info("Phase 10: Re-capture reports screenshots (with scan data)")
    results["phase10_reports"] = run_script("capture.py", [
        "--portal", args.portal,
        "--deployment", args.deployment,
        "--scanning", args.scanning,
        "--scanning-password", scanning_pw,
        "--output", str(img_output),
    ], log, timeout=600)

    # ── Summary ───────────────────────────────────────────────
    elapsed = time.time() - start_time
    elapsed_min = int(elapsed // 60)
    elapsed_sec = int(elapsed % 60)

    log.info("")
    log.info("=" * 60)
    log.info("  CAPTURE COMPLETE")
    log.info("=" * 60)
    log.info(f"  Total time: {elapsed_min}m {elapsed_sec}s")
    log.info("")

    passed = 0
    failed = 0
    skipped = 0
    for phase, result in results.items():
        if result == "skipped":
            icon = "SKIP"
            skipped += 1
        elif result:
            icon = "PASS"
            passed += 1
        else:
            icon = "FAIL"
            failed += 1
        log.info(f"  [{icon}] {phase}")

    log.info("")
    log.info(f"  {passed} passed, {failed} failed, {skipped} skipped")

    # List output files
    log.info("")
    log.info("  Screenshots:")
    for f in sorted(img_output.rglob("*.jpg")):
        log.info(f"    {f.relative_to(img_output)}")
    log.info("")
    log.info("  Videos:")
    for f in sorted(video_output.glob("*.mp4")):
        log.info(f"    {f.name}")

    if failed > 0:
        log.info("")
        log.info(f"  See {log_file} for details on failures")


if __name__ == "__main__":
    main()
