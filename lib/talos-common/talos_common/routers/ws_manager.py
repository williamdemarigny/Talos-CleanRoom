"""Shared WebSocket connection manager and message utilities for all routers."""

from datetime import datetime
from typing import Set

from fastapi import WebSocket


class ConnectionManager:
    """Shared WebSocket connection manager for all routers."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        disconnected = set()
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for conn in disconnected:
            self.active_connections.discard(conn)


def create_message(msg_type: str, data: dict) -> dict:
    return {
        "type": msg_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }


def make_broadcast_callback(manager: ConnectionManager, msg_type: str):
    """Factory for creating broadcast callbacks."""
    async def callback(entry):
        message = create_message(msg_type, entry if isinstance(entry, dict) else {"message": str(entry)})
        await manager.broadcast(message)
    return callback
