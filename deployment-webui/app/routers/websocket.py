"""WebSocket router for real-time deployment updates."""

import json
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel

from app.config import get_settings, Settings
from app.auth import decode_token
from app.services.deployment_service import get_deployment_service, DeploymentService
from app.models.deployment import LogEntry, DeploymentStep

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)


# Global connection manager
manager = ConnectionManager()


def create_message(msg_type: str, data: dict) -> dict:
    """Create a WebSocket message."""
    return {
        "type": msg_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }


async def log_callback(entry: LogEntry):
    """Callback for log entries - broadcasts to all clients."""
    message = create_message("log", {
        "step_id": entry.step_id,
        "level": entry.level,
        "message": entry.message,
        "timestamp": entry.timestamp.isoformat()
    })
    await manager.broadcast(message)


async def step_callback(step: DeploymentStep):
    """Callback for step updates - broadcasts to all clients."""
    message = create_message("step_update", {
        "step_id": step.id,
        "name": step.name,
        "description": step.description,
        "status": step.status.value,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "error_message": step.error_message
    })
    await manager.broadcast(message)


@router.websocket("/ws/deployment")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = None
):
    """WebSocket endpoint for deployment updates."""
    settings = get_settings()

    # Authenticate via token query parameter or cookie
    if not token:
        # Try to get from cookie
        cookies = websocket.cookies
        token = cookies.get("access_token")

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return

    user = decode_token(token, settings)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(websocket)

    # Get deployment service and register callbacks
    service = get_deployment_service()
    service.log_callback = log_callback
    service.step_callback = step_callback

    try:
        # Send initial status
        deployment = service.get_status()
        if deployment:
            await websocket.send_json(create_message("initial_state", {
                "id": deployment.id,
                "status": deployment.status.value,
                "current_step": deployment.current_step,
                "steps": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "status": s.status.value,
                        "started_at": s.started_at.isoformat() if s.started_at else None,
                        "completed_at": s.completed_at.isoformat() if s.completed_at else None
                    }
                    for s in deployment.steps
                ],
                "logs": [
                    {
                        "step_id": log.step_id,
                        "level": log.level,
                        "message": log.message,
                        "timestamp": log.timestamp.isoformat()
                    }
                    for log in service.logs
                ]
            }))
        else:
            await websocket.send_json(create_message("initial_state", {
                "status": "idle",
                "current_step": 0,
                "steps": [],
                "logs": []
            }))

        # Keep connection alive and handle client messages
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                # Handle client commands
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "start":
                    if not service.is_running():
                        await service.start_deployment(
                            log_callback=log_callback,
                            step_callback=step_callback
                        )
                        await websocket.send_json(create_message("started", {}))
                elif message.get("type") == "abort":
                    if service.is_running():
                        await service.abort_deployment()
                        await websocket.send_json(create_message("aborted", {}))

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                continue

    finally:
        manager.disconnect(websocket)
