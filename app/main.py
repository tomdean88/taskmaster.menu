from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import admin, ballot, join
from app.config import PUBLIC_URL
from app.db import PHOTO_DIR, init_db
from app.ws import manager

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts, before any requests are served.
    init_db()
    if "localhost" in PUBLIC_URL or "127.0.0.1" in PUBLIC_URL:
        print(f"WARNING: PUBLIC_URL is {PUBLIC_URL}. Phones can't use that QR code. Check .env.")
    yield


app = FastAPI(title="Taskmaster Menu", lifespan=lifespan)
app.include_router(join.router)
app.include_router(admin.router)
app.include_router(admin.protected)
app.include_router(ballot.router)

# StaticFiles checks that its folder exists the moment it is created,
# which happens before lifespan runs. Create it here so a fresh machine
# (like the Fedora laptop) doesn't crash on first start.
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    """Anyone who types the bare address lands on the join page."""
    return RedirectResponse("/join")


@app.get("/health")
def health():
    """Quick check that the server is up. Handy at the venue."""
    return {"status": "ok"}


@app.get("/qr.svg")
def join_qr():
    """The join QR code for central, built from PUBLIC_URL."""
    img = qrcode.make(f"{PUBLIC_URL}/join", image_factory=qrcode.image.svg.SvgPathImage)
    return Response(img.to_string(), media_type="image/svg+xml")


@app.get("/join")
def join_page():
    return FileResponse(STATIC_DIR / "join.html")


@app.get("/central")
def central_page():
    return FileResponse(STATIC_DIR / "central.html")


@app.websocket("/ws/central")
async def central_socket(websocket: WebSocket):
    await manager.connect(websocket, "central")
    try:
        await manager.send_state(websocket)
        while True:
            # Central never sends us anything. Waiting here keeps the
            # connection open and tells us the moment it closes.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        # Browsers can't put headers on a WebSocket, and URLs end up in logs,
        # so the admin token arrives as the first message instead.
        first = await websocket.receive_json()
        token = first.get("token") if isinstance(first, dict) else None
        if not admin.is_valid_session(token):
            await websocket.close(code=4401)  # tells the page to show the login screen
            return
        manager.add(websocket, "admin")
        await manager.send_state(websocket)
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        manager.disconnect(websocket)


@app.get("/play")
def play_page():
    return FileResponse(STATIC_DIR / "play.html")


@app.websocket("/ws/player")
async def player_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        first = await websocket.receive_json()
        token = first.get("token") if isinstance(first, dict) else None
        player_id = join.player_id_for_token(token)
        if player_id is None:
            await websocket.close(code=4401)  # unknown token: the page sends them to /join
            return
        manager.add(websocket, "player", player_id)
        await manager.send_state(websocket)
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        manager.disconnect(websocket)