"""
Mock data and route interception for transient UI states.

Used by capture.py for screenshots that require dynamic states
(e.g., deployment mid-flight, scan in progress) that can't be captured
from a static live instance.

Usage:
    from mock_data import mock_deployment_running, mock_scan_running

    await mock_deployment_running(page)
    await capture(page, output, "deployment-running-midflight.jpg")
"""

from playwright.async_api import Page, Route
import json


async def mock_deployment_running(page: Page, current_step: int = 9) -> None:
    """Intercept deployment status to show a running deployment at a given step.

    Steps 0..(current_step-1) show as completed, current_step as running,
    rest as pending.
    """
    steps = []
    for i in range(23):
        if i < current_step:
            status = "success"
        elif i == current_step:
            status = "running"
        else:
            status = "pending"
        steps.append({
            "id": i,
            "name": f"step_{i}",
            "description": f"Step {i}",
            "status": status,
            "started_at": "2025-01-01T12:00:00" if status != "pending" else None,
            "completed_at": "2025-01-01T12:01:00" if status == "success" else None,
            "error_message": None,
        })

    mock_state = {
        "id": "mock-deployment",
        "status": "running",
        "current_step": current_step,
        "steps": steps,
        "started_at": "2025-01-01T12:00:00",
        "completed_at": None,
        "error_message": None,
    }

    async def handle_status(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(mock_state),
        )

    await page.route("**/api/deployment/status", handle_status)
    # Block WebSocket to prevent connection errors
    await page.route("**/ws/**", lambda route: route.abort())


async def mock_deployment_failed(page: Page, failed_step: int = 5) -> None:
    """Intercept deployment status to show a failed deployment."""
    steps = []
    for i in range(23):
        if i < failed_step:
            status = "success"
        elif i == failed_step:
            status = "failed"
        else:
            status = "pending"
        steps.append({
            "id": i,
            "name": f"step_{i}",
            "description": f"Step {i}",
            "status": status,
            "started_at": "2025-01-01T12:00:00" if i <= failed_step else None,
            "completed_at": "2025-01-01T12:01:00" if status == "success" else None,
            "error_message": "Connection timed out waiting for node response"
            if status == "failed" else None,
        })

    mock_state = {
        "id": "mock-deployment",
        "status": "failed",
        "current_step": failed_step,
        "steps": steps,
        "started_at": "2025-01-01T12:00:00",
        "completed_at": None,
        "error_message": f"Step {failed_step} failed",
    }

    async def handle_status(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(mock_state),
        )

    await page.route("**/api/deployment/status", handle_status)
    await page.route("**/ws/**", lambda route: route.abort())


async def mock_scan_running(page: Page) -> None:
    """Intercept scan status to show a scan in progress."""
    mock_state = {
        "id": "mock-scan",
        "target": "10.83.3.0/24",
        "profile": "standard",
        "tools": [
            {
                "tool": "nmap",
                "status": "completed",
                "started_at": "2025-01-01T12:00:00",
                "completed_at": "2025-01-01T12:02:00",
                "error_message": None,
                "findings_count": 47,
                "uploaded_to_faraday": True,
            },
            {
                "tool": "openvas",
                "status": "running",
                "started_at": "2025-01-01T12:02:00",
                "completed_at": None,
                "error_message": None,
                "findings_count": 12,
                "uploaded_to_faraday": False,
            },
            {
                "tool": "metasploit",
                "status": "idle",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
                "findings_count": 0,
                "uploaded_to_faraday": False,
            },
        ],
        "status": "running",
        "started_at": "2025-01-01T12:00:00",
        "completed_at": None,
    }

    async def handle_status(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(mock_state),
        )

    await page.route("**/api/scan/status", handle_status)
    await page.route("**/ws/**", lambda route: route.abort())
