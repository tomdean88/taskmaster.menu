"""Judges lock in their star scores for the active task."""
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.db import connect
from app.ws import manager

router = APIRouter(prefix="/api")


class Score(BaseModel):
    performer_id: int
    stars: int = Field(ge=1, le=5)


class BallotBody(BaseModel):
    task_id: int
    scores: list[Score]


@router.post("/ballot")
async def lock_in_ballot(body: BallotBody, x_player_token: Annotated[str, Header()]):
    conn = connect()
    try:
        judge = conn.execute(
            "SELECT id, group_id FROM players WHERE token = ? AND removed = 0",
            (x_player_token,),
        ).fetchone()
        if judge is None:
            raise HTTPException(401, "Player not found.")

        task = conn.execute(
            "SELECT id, stage, group_id, status FROM tasks WHERE id = ?", (body.task_id,)
        ).fetchone()
        if task is None or task["status"] != "active":
            raise HTTPException(400, "Voting for that task has closed.")
        if task["stage"] != "group" or judge["group_id"] == task["group_id"]:
            raise HTTPException(403, "You aren't judging this task.")

        expected = {
            row["player_id"]
            for row in conn.execute(
                """SELECT task_performers.player_id
                   FROM task_performers
                   JOIN players ON players.id = task_performers.player_id
                   WHERE task_performers.task_id = ?
                     AND task_performers.status = 'in'
                     AND players.removed = 0""",
                (task["id"],),
            )
        }
        submitted = {s.performer_id for s in body.scores}
        if submitted != expected or len(body.scores) != len(expected):
            raise HTTPException(400, "Score every performer before locking in.")

        # Replace this judge's ballot in ONE transaction: old rows out, new rows in.
        conn.execute(
            "DELETE FROM scores WHERE task_id = ? AND judge_id = ?",
            (task["id"], judge["id"]),
        )
        conn.executemany(
            "INSERT INTO scores (task_id, judge_id, performer_id, stars) VALUES (?, ?, ?, ?)",
            [(task["id"], judge["id"], s.performer_id, s.stars) for s in body.scores],
        )
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast()
    return {"ok": True}