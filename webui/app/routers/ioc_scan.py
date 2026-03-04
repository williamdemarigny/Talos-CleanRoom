"""IOC Scan API router with REST endpoints and WebSocket for real-time updates."""

import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user, decode_token
from app.config import get_settings
from app.services.ioc_scan_service import get_ioc_scan_service, IocScanService
from app.models.ioc_scan import IocScanRequest, IocScanLogEntry, IocScanState
from .ws_manager import ConnectionManager, create_message

router = APIRouter()


ioc_manager = ConnectionManager()


async def ioc_log_callback(entry: IocScanLogEntry):
    """Broadcast IOC scan log entries to all connected clients."""
    message = create_message("ioc_log", {
        "level": entry.level,
        "message": entry.message,
        "timestamp": entry.timestamp.isoformat()
    })
    await ioc_manager.broadcast(message)


async def ioc_status_callback(scan_state: IocScanState):
    """Broadcast scan state updates to all connected clients."""
    message = create_message("ioc_status_update", {
        "id": scan_state.id,
        "status": scan_state.status.value,
        "target": scan_state.target,
        "mount_type": scan_state.mount_type.value,
        "scan_path": scan_state.scan_path,
        "started_at": scan_state.started_at.isoformat() if scan_state.started_at else None,
        "completed_at": scan_state.completed_at.isoformat() if scan_state.completed_at else None,
        "alerts_count": scan_state.alerts_count,
        "warnings_count": scan_state.warnings_count,
        "notices_count": scan_state.notices_count,
        "total_findings": len(scan_state.findings),
        "uploaded_to_faraday": scan_state.uploaded_to_faraday,
        "error_message": scan_state.error_message,
    })
    await ioc_manager.broadcast(message)


# =============================================================================
# REST Endpoints
# =============================================================================

class IocScanResponse(BaseModel):
    success: bool
    message: str
    scan_id: Optional[str] = None


class IocScanStatusResponse(BaseModel):
    status: str
    scan: Optional[dict] = None
    is_running: bool


@router.post("/start", response_model=IocScanResponse)
async def start_ioc_scan(
    request: IocScanRequest,
    user: dict = Depends(get_current_user)
):
    """Start a new IOC scan."""
    service = get_ioc_scan_service()

    if service.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An IOC scan is already in progress"
        )

    if not request.target.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target is required"
        )

    # Validate mount-specific fields
    if request.mount_type.value == "ssh" and not request.ssh_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSH username is required for SSH mount"
        )

    if request.mount_type.value == "smb" and not request.smb_share:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMB share name is required for SMB mount"
        )

    try:
        scan = await service.start_scan(
            request=request,
            log_callback=ioc_log_callback,
            status_callback=ioc_status_callback
        )
        return IocScanResponse(
            success=True,
            message="IOC scan started",
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


@router.post("/abort", response_model=IocScanResponse)
async def abort_ioc_scan(
    user: dict = Depends(get_current_user)
):
    """Abort the current IOC scan."""
    service = get_ioc_scan_service()

    if not service.is_running():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No IOC scan in progress"
        )

    success = await service.abort_scan()
    return IocScanResponse(
        success=success,
        message="IOC scan aborted" if success else "Failed to abort scan"
    )


@router.get("/status", response_model=IocScanStatusResponse)
async def get_ioc_scan_status(
    user: dict = Depends(get_current_user)
):
    """Get current IOC scan status."""
    service = get_ioc_scan_service()
    scan = service.get_status()

    if scan is None:
        return IocScanStatusResponse(
            status="idle",
            scan=None,
            is_running=False
        )

    return IocScanStatusResponse(
        status=scan.status.value,
        scan={
            "id": scan.id,
            "target": scan.target,
            "mount_type": scan.mount_type.value,
            "scan_path": scan.scan_path,
            "status": scan.status.value,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "alerts_count": scan.alerts_count,
            "warnings_count": scan.warnings_count,
            "notices_count": scan.notices_count,
            "total_findings": len(scan.findings),
            "uploaded_to_faraday": scan.uploaded_to_faraday,
            "error_message": scan.error_message,
            "findings": [
                {
                    "severity": f.severity.value,
                    "score": f.score,
                    "file_path": f.file_path,
                    "rule_name": f.rule_name,
                    "description": f.description,
                    "matched_strings": f.matched_strings,
                    "hash_md5": f.hash_md5,
                    "hash_sha256": f.hash_sha256,
                    "tags": f.tags,
                }
                for f in scan.findings
            ],
        },
        is_running=service.is_running()
    )


@router.get("/history")
async def get_ioc_scan_history(
    user: dict = Depends(get_current_user)
):
    """Get IOC scan history."""
    service = get_ioc_scan_service()
    return {"history": service.scan_history}


@router.get("/logs")
async def get_ioc_scan_logs(
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(get_current_user)
):
    """Get IOC scan logs."""
    service = get_ioc_scan_service()
    logs = service.logs
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
async def ioc_scan_websocket(
    websocket: WebSocket,
    token: str = None
):
    """WebSocket endpoint for real-time IOC scan updates."""
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

    await ioc_manager.connect(websocket)

    # Register callbacks on the service
    service = get_ioc_scan_service()
    service.log_callback = ioc_log_callback
    service.status_callback = ioc_status_callback

    try:
        # Send initial state
        scan = service.get_status()
        if scan:
            await websocket.send_json(create_message("ioc_initial_state", {
                "id": scan.id,
                "target": scan.target,
                "mount_type": scan.mount_type.value,
                "scan_path": scan.scan_path,
                "status": scan.status.value,
                "started_at": scan.started_at.isoformat() if scan.started_at else None,
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                "alerts_count": scan.alerts_count,
                "warnings_count": scan.warnings_count,
                "notices_count": scan.notices_count,
                "total_findings": len(scan.findings),
                "uploaded_to_faraday": scan.uploaded_to_faraday,
                "error_message": scan.error_message,
                "findings": [
                    {
                        "severity": f.severity.value,
                        "score": f.score,
                        "file_path": f.file_path,
                        "rule_name": f.rule_name,
                        "description": f.description,
                        "matched_strings": f.matched_strings,
                        "hash_md5": f.hash_md5,
                        "hash_sha256": f.hash_sha256,
                        "tags": f.tags,
                    }
                    for f in scan.findings
                ],
                "logs": [
                    {
                        "level": log.level,
                        "message": log.message,
                        "timestamp": log.timestamp.isoformat()
                    }
                    for log in service.logs
                ]
            }))
        else:
            await websocket.send_json(create_message("ioc_initial_state", {
                "status": "idle",
                "findings": [],
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
        ioc_manager.disconnect(websocket)
