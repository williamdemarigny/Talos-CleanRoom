# Screenshot & Video Capture Tool

Automated screenshot and video capture for the Talos CleanRoom User Guide using Playwright.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Capturing Screenshots

Run against the live deployment to capture all static screenshots:

```bash
python capture.py \
  --portal https://cleanroom.knowledgeondemand.net \
  --deployment https://10.83.3.190:8000 \
  --scanning https://scan.knowledgeondemand.net \
  --output ../docs/img
```

This captures ~27 screenshots from the current app state (Phase A). For transient states (deployment running, scan in progress), run the tool during those operations or use the mock data module.

### Using Mock Data for Transient States

```python
from capture import login, capture, wait_for_alpine
from mock_data import mock_deployment_running, mock_scan_running

# In your capture script:
await mock_deployment_running(page, current_step=9)
await page.goto(f"{DEPLOYMENT_URL}/deployment", wait_until="networkidle")
await capture(page, output, "deployment-running-midflight.jpg")
```

## Recording Videos

```bash
python video_recorder.py \
  --portal https://cleanroom.knowledgeondemand.net \
  --deployment https://10.83.3.190:8000 \
  --scanning https://scan.knowledgeondemand.net \
  --output ./videos
```

Videos 1 (Getting Started) and 5 (Reports Tour) are recorded against the current state. Videos 2-4 should be recorded during live operations.

## Post-Processing Videos

Requires FFmpeg (`choco install ffmpeg` on Windows).

```bash
# Convert WebM to MP4
ffmpeg -i video.webm -c:v libx264 -crf 23 -preset medium -c:a aac output.mp4

# Burn in subtitles
ffmpeg -i output.mp4 -vf subtitles=subs.srt output_subtitled.mp4

# Speed up slow sections (4x)
ffmpeg -i output.mp4 -filter:v "setpts=0.25*PTS" output_fast.mp4
```

## Output

- Screenshots: JPEG quality 85, 2560x1600 pixels (1280x800 viewport at 2x scale)
- Videos: WebM (convert to MP4 for browser compatibility)
- Subtitles: SRT format, generated from action timestamps
- Manifest: `screenshots_manifest.json` with capture date and URLs

## Regenerating

To update screenshots after UI changes, re-run `capture.py`. The manifest file tracks when screenshots were last captured.
