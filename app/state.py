"""Builds the snapshot each screen receives. Each audience only gets what it may see."""
from app.config import PUBLIC_URL
from app.db import connect


def player_to_dict(row) -> dict:
    """The public view of a player. The token is never included."""
    return {
        "id": row["id"],
        "name": row["name"],
        "group_id": row["group_id"],
        "photo_url": f"/photos/{row['photo_path']}" if row["photo_path"] else None,
    }


def get_setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def player_totals(conn) -> dict[int, int]:
    """Total points per player id. Placeholder until scoring arrives in Phase 6."""
    return {}


def build_central_state() -> dict:
    conn = connect()
    try:
        mode = get_setting(conn, "tv_mode")
        groups = conn.execute(
            "SELECT id, name FROM player_groups ORDER BY sort_order"
        ).fetchall()
        players = conn.execute(
            "SELECT * FROM players WHERE removed = 0 ORDER BY id"
        ).fetchall()
        task = conn.execute(
            """SELECT tasks.title, player_groups.name AS group_name
               FROM tasks
               LEFT JOIN player_groups ON player_groups.id = tasks.group_id
               WHERE tasks.status = 'active'"""
        ).fetchone()
        totals = player_totals(conn)
    finally:
        conn.close()

    boards = []
    for group in groups:
        members = []
        for row in players:
            if row["group_id"] == group["id"]:
                player = player_to_dict(row)
                player["points"] = totals.get(row["id"], 0)
                members.append(player)
        members.sort(key=lambda p: (-p["points"], p["name"].lower()))
        boards.append({"id": group["id"], "name": group["name"], "players": members})

    return {
        "audience": "central",
        "mode": mode,
        "join_url": f"{PUBLIC_URL}/join",
        "current_task": dict(task) if task else None,
        "joined_order": [player_to_dict(row) for row in players],
        "boards": boards,
    }


def build_state(audience: str) -> dict:
    if audience == "central":
        return build_central_state()
    raise ValueError(f"Unknown audience: {audience}")