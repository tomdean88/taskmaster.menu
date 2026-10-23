"""Tracks open WebSocket connections and pushes state snapshots to them."""
from fastapi import WebSocket

from app.state import build_central_state, build_state

# Who is watching: (audience, player_id). player_id is only set for players.
Viewer = tuple[str, int | None]


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[WebSocket, Viewer] = {}

    async def connect(self, websocket: WebSocket, audience: str, player_id: int | None = None) -> None:
        await websocket.accept()
        self.add(websocket, audience, player_id)

    def add(self, websocket: WebSocket, audience: str, player_id: int | None = None) -> None:
        """Register a socket that is already accepted (and, for admin or players, verified)."""
        self.connections[websocket] = (audience, player_id)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.pop(websocket, None)

    async def send_state(self, websocket: WebSocket) -> None:
        await websocket.send_json(build_state(*self.connections[websocket]))

    async def broadcast(self) -> None:
        """Send every connected screen a fresh snapshot of the current state."""
        central = build_central_state()  # built ONCE, then shared by every snapshot
        snapshots: dict[Viewer, dict] = {}
        for websocket, viewer in list(self.connections.items()):
            if viewer not in snapshots:
                snapshots[viewer] = build_state(*viewer, central=central)
            try:
                await websocket.send_json(snapshots[viewer])
            except Exception:
                self.disconnect(websocket)

manager = ConnectionManager()