"""Lauren's controls. Every route on `protected` requires a valid admin session."""
import asyncio
import secrets
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import ADMIN_PASSWORD
from app.db import connect
from app.ws import manager

LOGIN_FAIL_DELAY = 1  # seconds; tests set this to 0

# ---------- Sessions ----------

def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if not is_valid_session(x_admin_token):
        raise HTTPException(401, "Admin login required.")


# Public: only the login route lives here.
router = APIRouter(prefix="/api/admin")

# Protected: the dependency runs before EVERY route on this router.
protected = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class LoginBody(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginBody):
    # Fail closed: if no password is configured, nobody gets in.
    if not ADMIN_PASSWORD or not secrets.compare_digest(
        body.password.encode(), ADMIN_PASSWORD.encode()
    ):
        await asyncio.sleep(LOGIN_FAIL_DELAY)  # makes password guessing painfully slow
        raise HTTPException(401, "Wrong password.")

    token = secrets.token_urlsafe(32)
    conn = connect()
    try:
        conn.execute("INSERT INTO admin_sessions (token) VALUES (?)", (token,))
        conn.commit()
    finally:
        conn.close()
    return {"token": token}


# ---------- Helpers ----------

def clean_text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(400, f"{label} cannot be empty.")
    return value


def get_task_status(conn, task_id: int) -> str:
    row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found.")
    return row["status"]


# ---------- TV mode ----------

class TvModeBody(BaseModel):
    mode: Literal["lobby", "game", "results", "champion"]


@protected.put("/tv-mode")
async def set_tv_mode(body: TvModeBody):
    conn = connect()
    try:
        conn.execute(
            "UPDATE settings SET value = ? WHERE key = 'tv_mode'", (body.mode,)
        )
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


# ---------- Groups ----------

class GroupBody(BaseModel):
    name: str = Field(max_length=24)


@protected.patch("/groups/{group_id}")
async def rename_group(group_id: int, body: GroupBody):
    name = clean_text(body.name, "Group name")
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE player_groups SET name = ? WHERE id = ?", (name, group_id)
        )
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "Group not found.")
    await manager.broadcast()
    return {"ok": True}


# ---------- Players ----------

class PlayerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=24)
    group_id: int | None = None
    removed: bool | None = None


@protected.patch("/players/{player_id}")
async def update_player(player_id: int, body: PlayerUpdate):
    conn = connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(404, "Player not found.")
        if body.name is not None:
            conn.execute(
                "UPDATE players SET name = ? WHERE id = ?",
                (clean_text(body.name, "Name"), player_id),
            )
        if body.group_id is not None:
            conn.execute(
                "UPDATE players SET group_id = ? WHERE id = ?",
                (body.group_id, player_id),
            )
        if body.removed is not None:
            conn.execute(
                "UPDATE players SET removed = ? WHERE id = ?",
                (int(body.removed), player_id),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "That group does not exist.")
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


# ---------- Tasks ----------

class TaskCreate(BaseModel):
    title: str = Field(max_length=80)
    stage: Literal["group", "final"] = "group"
    group_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    group_id: int | None = None


class MoveBody(BaseModel):
    direction: Literal["up", "down"]


@protected.post("/tasks")
async def create_task(body: TaskCreate):
    title = clean_text(body.title, "Task title")
    if body.stage == "group" and body.group_id is None:
        raise HTTPException(400, "Pick which group performs this task.")
    group_id = body.group_id if body.stage == "group" else None

    conn = connect()
    try:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM tasks"
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO tasks (title, stage, group_id, sort_order) VALUES (?, ?, ?, ?)",
            (title, body.stage, group_id, next_order),
        )
        conn.commit()
        new_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, "That group does not exist.")
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True, "id": new_id}


@protected.patch("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskUpdate):
    conn = connect()
    try:
        status = get_task_status(conn, task_id)
        if body.title is not None:
            conn.execute(
                "UPDATE tasks SET title = ? WHERE id = ?",
                (clean_text(body.title, "Task title"), task_id),
            )
        if body.group_id is not None:
            if status != "draft":
                raise HTTPException(400, "Only tasks that haven't started can change groups.")
            conn.execute(
                "UPDATE tasks SET group_id = ? WHERE id = ?", (body.group_id, task_id)
            )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "That group does not exist.")
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


def clear_task_activity(conn, task_id: int) -> None:
    """Remove a task's ballots and performer snapshot. Manual adjustments keep their points."""
    conn.execute("DELETE FROM scores WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM task_performers WHERE task_id = ?", (task_id,))
    conn.execute("UPDATE adjustments SET task_id = NULL WHERE task_id = ?", (task_id,))


@protected.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    conn = connect()
    try:
        if get_task_status(conn, task_id) == "active":
            raise HTTPException(400, "Cancel the task before deleting it.")
        clear_task_activity(conn, task_id)
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


@protected.post("/tasks/{task_id}/reset")
async def reset_task(task_id: int):
    """Send a started or finished task back to queue as a fresh draft."""
    conn = connect()
    try:
        if get_task_status(conn, task_id) == "draft":
            raise HTTPException(400, "This task hasn't started.")
        clear_task_activity(conn, task_id)
        conn.execute(
            "UPDATE tasks SET status = 'draft', opened_at = NULL, revealed_at = NULL WHERE id = ?",
            (task_id,),
        )
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


@protected.post("/tasks/{task_id}/move")
async def move_task(task_id: int, body: MoveBody):
    conn = connect()
    try:
        rows = conn.execute("SELECT id, status FROM tasks ORDER BY sort_order, id").fetchall()
        ids = [row["id"] for row in rows]
        # Only upcoming tasks can move, and they only swap with other upcoming tasks.
        movable = [row["id"] for row in rows if row["status"] != "revealed"]
        if task_id not in ids:
            raise HTTPException(404, "Task not found.")
        if task_id not in movable:
            raise HTTPException(400, "Completed tasks can't be moved.")
        k = movable.index(task_id)
        m = k - 1 if body.direction == "up" else k + 1
        if 0 <= m < len(movable):
            i, j = ids.index(movable[k]), ids.index(movable[m])
            ids[i], ids[j] = ids[j], ids[i]
            conn.executemany(
                "UPDATE tasks SET sort_order = ? WHERE id = ?",
                [(position, tid) for position, tid in enumerate(ids, start=1)],
            )
            conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}

# ---------- Task lifecycle ----------

class PerformerBody(BaseModel):
    status: Literal["in", "sat_out", "dq"]


@protected.post("/tasks/{task_id}/start")
async def start_task(task_id: int):
    conn = connect()
    try:
        task = conn.execute(
            "SELECT status, stage, group_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if task is None:
            raise HTTPException(404, "Task not found.")
        if task["status"] != "draft":
            raise HTTPException(400, "This task has already started.")

        if task["stage"] == "final":
            performers = conn.execute(
                """SELECT players.id
                   FROM finalists
                   JOIN players ON players.id = finalists.player_id
                   WHERE players.removed = 0"""
            ).fetchall()
            if len(performers) < 2:
                raise HTTPException(400, "Pick at least two finalists first.")
        else:
            performers = conn.execute(
                "SELECT id FROM players WHERE group_id = ? AND removed = 0",
                (task["group_id"],),
            ).fetchall()
            if not performers:
                raise HTTPException(400, "Nobody is in that group yet.")

        # One transaction: the status change and the snapshot succeed or fail together.
        conn.execute(
            "UPDATE tasks SET status = 'active', opened_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
        conn.executemany(
            "INSERT INTO task_performers (task_id, player_id) VALUES (?, ?)",
            [(task_id, p["id"]) for p in performers],
        )
        conn.execute("UPDATE settings SET value = 'game' WHERE key = 'tv_mode'")
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Another task is already running. Reveal it first.")
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


@protected.post("/tasks/{task_id}/reveal")
async def reveal_task(task_id: int):
    conn = connect()
    try:
        if get_task_status(conn, task_id) != "active":
            raise HTTPException(400, "Only a running task can be revealed.")
        conn.execute(
            "UPDATE tasks SET status = 'revealed', revealed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
        conn.execute("UPDATE settings SET value = 'results' WHERE key = 'tv_mode'")
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


@protected.post("/tasks/{task_id}/reopen")
async def reopen_task(task_id: int):
    conn = connect()
    try:
        if get_task_status(conn, task_id) != "revealed":
            raise HTTPException(400, "Only revealed tasks can be reopened.")
        conn.execute(
            "UPDATE tasks SET status = 'active', revealed_at = NULL WHERE id = ?",
            (task_id,),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Another task is already running. Reveal it first.")
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}


@protected.patch("/tasks/{task_id}/performers/{player_id}")
async def set_performer_status(task_id: int, player_id: int, body: PerformerBody):
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE task_performers SET status = ? WHERE task_id = ? AND player_id = ?",
            (body.status, task_id, player_id),
        )
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "That player isn't performing in this task.")
    await manager.broadcast()
    return {"ok": True}

@protected.delete("/tasks/{task_id}/ballots/{judge_id}")
async def reset_ballot(task_id: int, judge_id: int):
    conn = connect()
    try:
        get_task_status(conn, task_id)  # 404 if the task doesn't exist
        cursor = conn.execute(
            "DELETE FROM scores WHERE task_id = ? AND judge_id = ?", (task_id, judge_id)
        )
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "That judge has no ballot for this task.")
    await manager.broadcast()
    return {"ok": True}

# ---------- Point adjustments ----------

class AdjustmentBody(BaseModel):
    player_id: int
    points: int = Field(ge=-20, le=20)  # catches typos like 50 instead of 5
    reason: str = Field(default="", max_length=80)


@protected.post("/adjustments")
async def add_adjustment(body: AdjustmentBody):
    if body.points == 0:
        raise HTTPException(400, "An adjustment needs at least 1 point.")
    conn = connect()
    try:
        player = conn.execute(
            "SELECT removed FROM players WHERE id = ?", (body.player_id,)
        ).fetchone()
        if player is None or player["removed"]:
            raise HTTPException(400, "That player isn't in the game.")
        cursor = conn.execute(
            "INSERT INTO adjustments (player_id, points, reason) VALUES (?, ?, ?)",
            (body.player_id, body.points, body.reason.strip()),
        )
        conn.commit()
        new_id = cursor.lastrowid
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True, "id": new_id}


@protected.delete("/adjustments/{adjustment_id}")
async def delete_adjustment(adjustment_id: int):
    conn = connect()
    try:
        cursor = conn.execute("DELETE FROM adjustments WHERE id = ?", (adjustment_id,))
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "Adjustment not found.")
    await manager.broadcast()
    return {"ok": True}

# ---------- The final ----------

class FinalistsBody(BaseModel):
    player_ids: list[int] = Field(max_length=12)


@protected.put("/finalists")
async def set_finalists(body: FinalistsBody):
    """Replace the whole finalist list in one go."""
    player_ids = list(dict.fromkeys(body.player_ids))  # drop duplicates, keep order
    conn = connect()
    try:
        for pid in player_ids:
            row = conn.execute("SELECT removed FROM players WHERE id = ?", (pid,)).fetchone()
            if row is None or row["removed"]:
                raise HTTPException(400, "Finalists must be players who are in the game.")
        conn.execute("DELETE FROM finalists")
        conn.executemany(
            "INSERT INTO finalists (player_id) VALUES (?)", [(pid,) for pid in player_ids]
        )
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}