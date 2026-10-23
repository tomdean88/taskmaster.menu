import os
from contextlib import asynccontextmanager

import qrcode
import qrcode.image.svg
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app import join
from app.db import PHOTO_DIR, init_db

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts, before any requests are served.
    init_db()
    yield


app = FastAPI(title="Taskmaster Menu", lifespan=lifespan)
app.include_router(join.router)

# StaticFiles checks that its folder exists the moment it is created,
# which happens before lifespan runs. Create it here so a fresh machine
# (like the Fedora laptop) doesn't crash on first start.
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/join")
def join_page():
    return FileResponse(STATIC_DIR / "join.html")


@app.get("/health")
def health():
    """Quick check that the server is up. Handy at the venue."""
    return {"status": "ok"}


@app.get("/qr.svg")
def join_qr():
    """The join QR code for central, built from PUBLIC_URL."""
    img = qrcode.make(f"{PUBLIC_URL}/join", image_factory=qrcode.image.svg.SvgPathImage)
    return Response(img.to_string(), media_type="image/svg+xml")