"""Player join: list groups, join with a photo, and look yourself up."""
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.db import PHOTO_DIR, connect
from app.state import player_to_dict
from app.ws import manager

router = APIRouter(prefix="/api")

MAX_NAME_LENGTH = 24
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB ceiling; phones resize first, so real uploads are tiny
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.get("/groups")
def list_groups():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, name FROM player_groups ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


@router.post("/join")
async def join(
    name: Annotated[str, Form()],
    group_id: Annotated[int, Form()],
    photo: Annotated[UploadFile, File()],
):
    name = name.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise HTTPException(400, f"Name must be 1 to {MAX_NAME_LENGTH} characters.")

    extension = PHOTO_TYPES.get(photo.content_type)
    if extension is None:
        raise HTTPException(400, "Photo must be a JPEG, PNG, or WebP image.")

    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "Photo is too large.")

    conn = connect()
    try:
        group = conn.execute(
            "SELECT id FROM player_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if group is None:
            raise HTTPException(400, "That group does not exist.")

        filename = f"{uuid.uuid4().hex}{extension}"
        (PHOTO_DIR / filename).write_bytes(data)

        token = secrets.token_urlsafe(32)
        cursor = conn.execute(
            "INSERT INTO players (token, name, photo_path, group_id) VALUES (?, ?, ?, ?)",
            (token, name, filename, group_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM players WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    finally:
        conn.close()
    await manager.broadcast()
    return {"token": token, "player": player_to_dict(row)}


@router.get("/me")
def me(x_player_token: Annotated[str, Header()]):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM players WHERE token = ? AND removed = 0",
            (x_player_token,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "Player not found.")
    return player_to_dict(row)

def player_id_for_token(token: str | None) -> int | None:
    """Which player owns this token? Includes removed players, so they see a 'removed' screen."""
    if not token:
        return None
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM players WHERE token = ?", (token,)).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None