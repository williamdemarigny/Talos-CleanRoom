"""Scan API router with REST endpoints and WebSocket for real-time updates."""

import json
from typing import Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user, decode_token
from app.config import get_settings
from app.services.scan_service import get_scan_service, ScanService
from app.models.scan import (
    ScanRequest, ScanState, ScanStatus, ScanTool, ScanProfile,
    ScanToolState, ScanLogEntry
)
from .ws_manager import ConnectionManager, create_message

router = APIRouter()


scan_manager = ConnectionManager()


async def scan_log_callback(entry: ScanLogEntry):
    """Broadcast scan log entries to all connected clients."""
    message = create_message("scan_log", {
        "tool": entry.tool,
        "level": entry.level,
        "message": entry.message,
        "timestamp": entry.timestamp.isoformat()
    })
    await scan_manager.broadcast(message)


async def scan_tool_callback(tool_state: ScanToolState):
    """Broadcast tool state updates to all connected clients."""
    message = create_message("scan_tool_update", {
        "tool": tool_state.tool.value,
        "status": tool_state.status.value,
        "started_at": tool_state.started_at.isoformat() if tool_state.started_at else None,
        "completed_at": tool_state.completed_at.isoformat() if tool_state.completed_at else None,
        "error_message": tool_state.error_message,
        "findings_count": tool_state.findings_count,
        "uploaded_to_faraday": tool_state.uploaded_to_faraday
    })
    await scan_manager.broadcast(message)


# =============================================================================
# REST Endpoints
# =============================================================================

class ScanResponse(BaseModel):
    success: bool
    message: str
    scan_id: Optional[str] = None


class ScanStatusResponse(BaseModel):
    status: str
    scan: Optional[dict] = None
    is_running: bool


@router.post("/start", response_model=ScanResponse)
async def start_scan(
    request: ScanRequest,
    user: dict = Depends(get_current_user)
):
    """Start a new security scan."""
    service = get_scan_service()

    if service.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan is already in progress"
        )

    if not request.tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one scan tool must be selected"
        )

    if not request.target.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target is required"
        )

    try:
        scan = await service.start_scan(
            request=request,
            log_callback=scan_log_callback,
            tool_callback=scan_tool_callback
        )
        return ScanResponse(
            success=True,
            message="Scan started",
            scan_id=scan.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/abort", response_model=ScanResponse)
async def abort_scan(
    user: dict = Depends(get_current_user)
):
    """Abort the current scan."""
    service = get_scan_service()

    if not service.is_running():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No scan in progress"
        )

    success = await service.abort_scan()
    return ScanResponse(
        success=success,
        message="Scan aborted" if success else "Failed to abort scan"
    )


@router.get("/status", response_model=ScanStatusResponse)
async def get_scan_status(
    user: dict = Depends(get_current_user)
):
    """Get current scan status."""
    service = get_scan_service()
    scan = service.get_status()

    if scan is None:
        return ScanStatusResponse(
            status="idle",
            scan=None,
            is_running=False
        )

    return ScanStatusResponse(
        status=scan.status.value,
        scan={
            "id": scan.id,
            "target": scan.target,
            "profile": scan.profile.value,
            "status": scan.status.value,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "tools": [
                {
                    "tool": ts.tool.value,
                    "status": ts.status.value,
                    "started_at": ts.started_at.isoformat() if ts.started_at else None,
                    "completed_at": ts.completed_at.isoformat() if ts.completed_at else None,
                    "error_message": ts.error_message,
                    "findings_count": ts.findings_count,
                    "uploaded_to_faraday": ts.uploaded_to_faraday
                }
                for ts in scan.tools
            ]
        },
        is_running=service.is_running()
    )


@router.get("/history")
async def get_scan_history(
    user: dict = Depends(get_current_user)
):
    """Get scan history."""
    service = get_scan_service()
    return {"history": service.scan_history}


@router.get("/modules")
async def get_msf_modules(
    user: dict = Depends(get_current_user)
):
    """Return available Metasploit modules for custom profile selection."""
    service = get_scan_service()
    return {"modules": service.get_module_catalog()}


@router.get("/openvas-configs")
async def get_openvas_configs(
    user: dict = Depends(get_current_user)
):
    """Return available OpenVAS scan configs from GVM."""
    service = get_scan_service()
    return {"configs": await service.get_openvas_configs()}


@router.get("/openvas-families")
async def get_openvas_families(
    user: dict = Depends(get_current_user)
):
    """Return available OpenVAS NVT families from GVM."""
    service = get_scan_service()
    return {"families": await service.get_openvas_families()}


@router.get("/logs")
async def get_scan_logs(
    tool: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(get_current_user)
):
    """Get scan logs, optionally filtered by tool."""
    service = get_scan_service()
    logs = service.logs

    if tool:
        logs = [log for log in logs if log.tool == tool]

    total = len(logs)
    logs = logs[offset:offset + limit]

    return {
        "logs": [log.model_dump() for log in logs],
        "total": total
    }


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/ws")
async def scan_websocket(
    websocket: WebSocket,
    token: str = None
):
    """WebSocket endpoint for real-time scan updates."""
    settings = get_settings()

    # Authenticate
    if not token:
        cookies = websocket.cookies
        token = cookies.get("access_token")

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return

    user = decode_token(token, settings)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await scan_manager.connect(websocket)

    # Get scan service and register callbacks
    service = get_scan_service()
    service.log_callback = scan_log_callback
    service.tool_callback = scan_tool_callback

    try:
        # Send initial state
        scan = service.get_status()
        if scan:
            await websocket.send_json(create_message("scan_initial_state", {
                "id": scan.id,
                "target": scan.target,
                "profile": scan.profile.value,
                "status": scan.status.value,
                "started_at": scan.started_at.isoformat() if scan.started_at else None,
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                "tools": [
                    {
                        "tool": ts.tool.value,
                        "status": ts.status.value,
                        "started_at": ts.started_at.isoformat() if ts.started_at else None,
                        "completed_at": ts.completed_at.isoformat() if ts.completed_at else None,
                        "error_message": ts.error_message,
                        "findings_count": ts.findings_count,
                        "uploaded_to_faraday": ts.uploaded_to_faraday
                    }
                    for ts in scan.tools
                ],
                "logs": [
                    {
                        "tool": log.tool,
                        "level": log.level,
                        "message": log.message,
                        "timestamp": log.timestamp.isoformat()
                    }
                    for log in service.logs
                ]
            }))
        else:
            await websocket.send_json(create_message("scan_initial_state", {
                "status": "idle",
                "tools": [],
                "logs": []
            }))

        # Keep connection alive
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                continue

    finally:
        scan_manager.disconnect(websocket)
