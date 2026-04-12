# Screenshot & Video Capture Tool

Automated screenshot and video capture for the Talos CleanRoom User Guide using Playwright.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
choco install ffmpeg   # Windows — needed for video post-processing
```

## Full Capture Workflow

Run the tools in order after a deployment is up and all three apps are accessible.

### Phase A: Static Screenshots

Captures ~20 screenshots from the current app state (portal, deployment, scanning, target lab, reports):

```bash
python capture.py \
  --portal https://cleanroom.knowledgeondemand.net \
  --deployment https://10.83.3.190:8000 \
  --scanning https://scan.knowledgeondemand.net \
  --scanning-password "yourpassword" \
  --output ../docs/img
```

### Phase B: Transient State Screenshots

Captures ~14 screenshots using Playwright route interception to mock API responses (deployment idle/running/failed, scan running/completed, enrichment, Target Lab active/deploying):

```bash
python capture_remaining.py \
  --scanning-password "yourpassword" \
  --output ../docs/img
```

### Phase C: IOC Scan Screenshots

Captures 2 IOC scan screenshots (running + findings) with mocked data:

```bash
python capture_ioc.py \
  --scanning-password "yourpassword" \
  --output ../docs/img
```

### Phase D: Using Mock Data for Transient States

For states that can't be captured from a live instance, the tools use Playwright route interception to mock API responses. This is handled automatically by `capture_remaining.py` and `capture_ioc.py`.

To add custom mock states, use the pattern:

```python
from capture import login, capture, wait_for_alpine

# In your capture script:
await page.route("**/api/deployment/status", lambda r: r.fulfill(
    status=200, content_type="application/json",
    body=json.dumps(mock_state)))
await page.goto(f"{DEPLOYMENT_URL}/deployment", wait_until="networkidle")
await capture(page, output, "custom-state.jpg")
```

## Recording Videos

### Videos 1 & 5 (Static Walkthroughs)

These record against the current state — no live operations needed:

```bash
python video_recorder.py \
  --portal https://cleanroom.knowledgeondemand.net \
  --deployment https://10.83.3.190:8000 \
  --scanning https://scan.knowledgeondemand.net \
  --scanning-password "yourpassword" \
  --output ../docs/videos
```

### Video 2 (Deployment) — Requires Live Deployment

Run this **during** a fresh deployment. The recording captures the full deployment process:

```bash
python video_recorder.py --videos 2 \
  --deployment https://10.83.3.190:8000 \
  --output ../docs/videos
```

The raw video will be 30-60 minutes long. Speed it up in post-processing:

```bash
ffmpeg -i 02-deployment.mp4 -filter:v "setpts=0.1*PTS" -an 02-deployment-fast.mp4
```

### Video 3 (Vulnerability Scan) — Requires Live Scan

Run this to record a Quick vulnerability scan (~5 min):

```bash
python video_recorder.py --videos 3 \
  --scanning https://scan.knowledgeondemand.net \
  --scanning-password "yourpassword" \
  --output ../docs/videos
```

### Video 4 (IOC Scan) — Requires Live IOC Scan

Run this to record an IOC scan (~2-3 min):

```bash
python video_recorder.py --videos 4 \
  --scanning https://scan.knowledgeondemand.net \
  --scanning-password "yourpassword" \
  --output ../docs/videos
```

### Record All Static Videos at Once

```bash
python video_recorder.py --videos all \
  --scanning-password "yourpassword" \
  --output ../docs/videos
```

## Post-Processing Videos

Requires FFmpeg (`choco install ffmpeg` on Windows).

```bash
# Convert WebM to MP4
ffmpeg -i video.webm -c:v libx264 -crf 23 -preset medium -c:a aac output.mp4

# Burn in subtitles
ffmpeg -i output.mp4 -vf subtitles=subs.srt output_subtitled.mp4

# Speed up slow sections (10x)
ffmpeg -i output.mp4 -filter:v "setpts=0.1*PTS" -an output_fast.mp4
```

## Output

- **Screenshots:** JPEG quality 85, 2560x1600 pixels (1280x800 viewport at 2x scale)
- **Videos:** WebM raw → MP4 converted (5 videos total)
- **Subtitles:** SRT format, auto-generated from action timestamps
- **Manifest:** `screenshots_manifest.json` with capture date and URLs

## Video Index

| # | File | Content | Recording Mode |
|---|------|---------|---------------|
| 1 | `01-getting-started.mp4` | Portal login, navigation, SSO | Static (any time) |
| 2 | `02-deployment.mp4` | Full deployment walkthrough | Live (during deployment) |
| 3 | `03-vuln-scan.mp4` | Vulnerability scan walkthrough | Live (during Quick scan) |
| 4 | `04-ioc-scan.mp4` | IOC scan walkthrough | Live (during IOC scan) |
| 5 | `05-reports-tour.mp4` | Reports dashboard tour | Static (needs scan data) |

## Regenerating

To update screenshots after UI changes, re-run the capture scripts in order (A → B → C). The manifest file tracks when screenshots were last captured.
