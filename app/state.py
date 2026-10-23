"""Builds the snapshot each screen receives. Each audience only gets what it may see."""
from app.config import PUBLIC_URL
from app.db import connect
from app.scoring import task_points


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


def task_results(conn, task_id: int) -> dict[int, int]:
    """Points per performer for one task, calculated from the ballots."""
    performers = conn.execute(
        """SELECT task_performers.player_id, task_performers.status
           FROM task_performers
           JOIN players ON players.id = task_performers.player_id
           WHERE task_performers.task_id = ?
             AND task_performers.status != 'sat_out'
             AND players.removed = 0""",
        (task_id,),
    ).fetchall()

    stars: dict[int, list[int]] = {
        row["player_id"]: [] for row in performers if row["status"] == "in"
    }
    for row in conn.execute(
        """SELECT scores.performer_id, scores.stars
           FROM scores
           JOIN players AS judges ON judges.id = scores.judge_id
           WHERE scores.task_id = ? AND judges.removed = 0""",
        (task_id,),
    ):
        if row["performer_id"] in stars:
            stars[row["performer_id"]].append(row["stars"])

    points = task_points(stars)
    for row in performers:
        if row["status"] == "dq":
            points[row["player_id"]] = 0  # Greg's disqualification
    return points


def player_totals(conn) -> dict[int, int]:
    """Total group-stage points per player: revealed tasks plus Lauren's adjustments."""
    totals: dict[int, int] = {}
    revealed = conn.execute(
        "SELECT id FROM tasks WHERE status = 'revealed' AND stage = 'group'"
    ).fetchall()
    for task in revealed:
        for player_id, points in task_results(conn, task["id"]).items():
            totals[player_id] = totals.get(player_id, 0) + points
    for row in conn.execute(
        "SELECT player_id, SUM(points) AS points FROM adjustments GROUP BY player_id"
    ):
        totals[row["player_id"]] = totals.get(row["player_id"], 0) + row["points"]
    return totals

def build_player_state(player_id: int) -> dict:
    """One player's personal view. Never includes anyone else's scores."""
    conn = connect()
    try:
        me = conn.execute(
            "SELECT * FROM players WHERE id = ? AND removed = 0", (player_id,)
        ).fetchone()
        task = conn.execute(
            "SELECT id, title, stage, group_id FROM tasks WHERE status = 'active'"
        ).fetchone()
        performers = []
        my_scores = {}
        if me and task:
            performers = conn.execute(
                """SELECT players.*, task_performers.status AS performer_status
                   FROM task_performers
                   JOIN players ON players.id = task_performers.player_id
                   WHERE task_performers.task_id = ? AND players.removed = 0
                   ORDER BY players.name COLLATE NOCASE""",
                (task["id"],),
            ).fetchall()
            my_scores = {
                row["performer_id"]: row["stars"]
                for row in conn.execute(
                    "SELECT performer_id, stars FROM scores WHERE task_id = ? AND judge_id = ?",
                    (task["id"], player_id),
                )
            }
    finally:
        conn.close()

    if me is None:
        return {"audience": "player", "me": None}

    state = {"audience": "player", "me": player_to_dict(me), "task": None}
    if task is None:
        return state

    my_performer_status = next(
        (row["performer_status"] for row in performers if row["id"] == player_id), None
    )
    if my_performer_status in ("in", "dq"):
        role = "performer"
    elif task["stage"] == "group" and me["group_id"] != task["group_id"]:
        role = "judge"
    else:
        role = "spectator"  # sat out, or joined the performing group after the task started

    is_judge = role == "judge"
    state["task"] = {
        "id": task["id"],
        "title": task["title"],
        "role": role,
        "performers": [
            player_to_dict(row) for row in performers if row["performer_status"] == "in"
        ] if is_judge else [],
        "my_scores": my_scores if is_judge else {},
        "locked": is_judge and bool(my_scores),
    }
    return state


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
            """SELECT tasks.id, tasks.title, tasks.group_id, player_groups.name AS group_name
               FROM tasks
               LEFT JOIN player_groups ON player_groups.id = tasks.group_id
               WHERE tasks.status = 'active'"""
        ).fetchone()
        judge_count = locked_count = 0
        if task:
            judge_count = conn.execute(
                "SELECT COUNT(*) FROM players WHERE removed = 0 AND group_id != ?",
                (task["group_id"],),
            ).fetchone()[0]
            locked_count = conn.execute(
                """SELECT COUNT(DISTINCT scores.judge_id)
                   FROM scores
                   JOIN players ON players.id = scores.judge_id
                   WHERE scores.task_id = ? AND players.removed = 0 AND players.group_id != ?""",
                (task["id"], task["group_id"]),
            ).fetchone()[0]
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

    current_task = None
    if task:
        current_task = {
            "title": task["title"],
            "group_name": task["group_name"],
            "judge_count": judge_count,
            "locked_count": locked_count,
        }

    return {
        "audience": "central",
        "mode": mode,
        "join_url": f"{PUBLIC_URL}/join",
        "current_task": current_task,
        "joined_order": [player_to_dict(row) for row in players],
        "boards": boards,
    }

def build_admin_state() -> dict:
    """Everything central sees, plus the full player and task lists."""
    state = build_central_state()
    state["audience"] = "admin"
    conn = connect()
    try:
        players = conn.execute(
            "SELECT * FROM players ORDER BY name COLLATE NOCASE"
        ).fetchall()
        tasks = conn.execute(
            """SELECT tasks.id, tasks.title, tasks.stage, tasks.status, tasks.group_id,
                      player_groups.name AS group_name
               FROM tasks
               LEFT JOIN player_groups ON player_groups.id = tasks.group_id
               ORDER BY tasks.sort_order, tasks.id"""
        ).fetchall()
        performer_rows = conn.execute(
            """SELECT task_performers.task_id, task_performers.player_id,
                      task_performers.status, players.name
               FROM task_performers
               JOIN players ON players.id = task_performers.player_id
               ORDER BY players.name COLLATE NOCASE"""
        ).fetchall()
    finally:
        conn.close()

    # Everything below works on data we already fetched, so the connection can be closed.
    performers_by_task: dict[int, list[dict]] = {}
    for row in performer_rows:
        performers_by_task.setdefault(row["task_id"], []).append(
            {"player_id": row["player_id"], "name": row["name"], "status": row["status"]}
        )

    state["players"] = [
        {**player_to_dict(row), "removed": bool(row["removed"])} for row in players
    ]
    state["tasks"] = [
        {**dict(row), "performers": performers_by_task.get(row["id"], [])}
        for row in tasks
    ]
    state["groups"] = [{"id": b["id"], "name": b["name"]} for b in state["boards"]]
    return state


def build_state(audience: str, player_id: int | None = None) -> dict:
    if audience == "central":
        return build_central_state()
    if audience == "admin":
        return build_admin_state()
    if audience == "player" and player_id is not None:
        return build_player_state(player_id)
    raise ValueError(f"Unknown audience: {audience}")