"""Tracks open WebSocket connections and pushes state snapshots to them."""
from fastapi import WebSocket

from app.state import build_state


class ConnectionManager:
    def __init__(self) -> None:
        # Each open socket, mapped to who is watching: "central", "player", or "admin".
        self.connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, audience: str) -> None:
        await websocket.accept()
        self.connections[websocket] = audience

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.pop(websocket, None)

    async def send_state(self, websocket: WebSocket) -> None:
        await websocket.send_json(build_state(self.connections[websocket]))

    async def broadcast(self) -> None:
        """Send every connected screen a fresh snapshot of the current state."""
        snapshots: dict[str, dict] = {}
        for websocket, audience in list(self.connections.items()):
            if audience not in snapshots:
                snapshots[audience] = build_state(audience)
            try:
                await websocket.send_json(snapshots[audience])
            except Exception:
                self.disconnect(websocket)


manager = ConnectionManager()