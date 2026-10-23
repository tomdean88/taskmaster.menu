"""Builds the snapshot each screen receives. Each audience only gets what it may see."""
from app.config import PUBLIC_URL
from app.db import connect
from app.scoring import task_points, trimmed_total


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


def task_breakdown(conn, task_id: int) -> dict[int, dict]:
    """Per performer: trimmed judge total, points, and status. Sat-out players are left out."""
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
    breakdown = {}
    for row in performers:
        pid = row["player_id"]
        if row["status"] == "dq":
            breakdown[pid] = {"total": None, "points": 0, "status": "dq"}  # Greg's disqualification
        else:
            breakdown[pid] = {"total": trimmed_total(stars[pid]), "points": points[pid], "status": "in"}
    return breakdown


def task_results(conn, task_id: int) -> dict[int, int]:
    """Points per performer for one task."""
    return {pid: result["points"] for pid, result in task_breakdown(conn, task_id).items()}


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

def build_player_state(player_id: int, central: dict | None = None) -> dict:
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
        result_rows = []
        my_points = {}
        bonus = 0
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
        if me:
            result_rows = conn.execute(
                """SELECT tasks.id, tasks.title, task_performers.status
                   FROM task_performers
                   JOIN tasks ON tasks.id = task_performers.task_id
                   WHERE task_performers.player_id = ?
                     AND tasks.status = 'revealed' AND tasks.stage = 'group'
                   ORDER BY tasks.sort_order""",
                (player_id,),
            ).fetchall()
            my_points = {
                row["id"]: task_results(conn, row["id"]).get(player_id, 0)
                for row in result_rows
                if row["status"] != "sat_out"
            }
            bonus = conn.execute(
                "SELECT COALESCE(SUM(points), 0) FROM adjustments WHERE player_id = ?",
                (player_id,),
            ).fetchone()[0]
    finally:
        conn.close()

    if me is None:
        return {"audience": "player", "me": None}

    central = central or build_central_state()
    my_results = []
    for row in result_rows:
        if row["status"] == "sat_out":
            my_results.append({"title": row["title"], "points": None, "note": "Sat out"})
        else:
            my_results.append({
                "title": row["title"],
                "points": my_points[row["id"]],
                "note": "DQ" if row["status"] == "dq" else "",
            })

    state = {
        "audience": "player",
        "me": player_to_dict(me),
        "task": None,
        "boards": central["boards"],  # the same public leaderboard the TV shows
        "up_next": central["up_next"],
        "my_results": my_results,
        "bonus": bonus,
    }
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
        up_next = conn.execute(
            """SELECT tasks.stage, tasks.group_id, player_groups.name AS group_name
               FROM tasks
               LEFT JOIN player_groups ON player_groups.id = tasks.group_id
               WHERE tasks.status = 'draft'
               ORDER BY tasks.sort_order, tasks.id
               LIMIT 1"""
        ).fetchone()
        last = conn.execute(
            """SELECT tasks.id, tasks.title, player_groups.name AS group_name
               FROM tasks
               LEFT JOIN player_groups ON player_groups.id = tasks.group_id
               WHERE tasks.status = 'revealed' AND tasks.stage = 'group'
               ORDER BY tasks.revealed_at DESC, tasks.id DESC
               LIMIT 1"""
        ).fetchone()
        last_breakdown = task_breakdown(conn, last["id"]) if last else {}
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

    last_result = None
    if last:
        players_by_id = {row["id"]: row for row in players}
        rows = [
            {**player_to_dict(players_by_id[pid]), **result}
            for pid, result in last_breakdown.items()
            if pid in players_by_id
        ]
        rows.sort(key=lambda r: (-r["points"], -(r["total"] or 0), r["name"].lower()))
        last_result = {"title": last["title"], "group_name": last["group_name"], "rows": rows}

    return {
        "audience": "central",
        "mode": mode,
        "join_url": f"{PUBLIC_URL}/join",
        "current_task": current_task,
        "up_next": dict(up_next) if up_next else None,
        "last_result": last_result,
        "joined_order": [player_to_dict(row) for row in players],
        "boards": boards,
    }

def build_admin_state(central: dict | None = None) -> dict:
    """Everything central sees, plus full player, task, and ballot lists."""
    state = dict(central) if central else build_central_state()
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
        score_rows = conn.execute(
            """SELECT scores.task_id, scores.judge_id, scores.stars,
                      performers.name AS performer_name
               FROM scores
               JOIN players AS performers ON performers.id = scores.performer_id
               ORDER BY performers.name COLLATE NOCASE"""
        ).fetchall()
        adjustment_rows = conn.execute(
            """SELECT adjustments.id, adjustments.player_id, adjustments.points,
                      adjustments.reason, players.name AS player_name
               FROM adjustments
               JOIN players ON players.id = adjustments.player_id
               ORDER BY adjustments.id DESC"""
        ).fetchall()
    finally:
        conn.close()

    # Everything below works on data we already fetched, so the connection can be closed.
    players_by_id = {row["id"]: row for row in players}

    performers_by_task: dict[int, list[dict]] = {}
    for row in performer_rows:
        performers_by_task.setdefault(row["task_id"], []).append(
            {"player_id": row["player_id"], "name": row["name"], "status": row["status"]}
        )

    # task id -> judge id -> the scores that judge gave
    ballots: dict[int, dict[int, list[dict]]] = {}
    for row in score_rows:
        ballots.setdefault(row["task_id"], {}).setdefault(row["judge_id"], []).append(
            {"performer": row["performer_name"], "stars": row["stars"]}
        )

    def judges_for(task) -> list[dict]:
        """Everyone who should judge this task, plus anyone who has a ballot in it."""
        if task["status"] == "draft" or task["stage"] != "group":
            return []
        task_ballots = ballots.get(task["id"], {})
        judge_ids = [
            row["id"] for row in players
            if not row["removed"] and row["group_id"] != task["group_id"]
        ]
        judge_ids += [jid for jid in task_ballots if jid not in judge_ids]
        return [
            {
                "player_id": jid,
                "name": players_by_id[jid]["name"],
                "removed": bool(players_by_id[jid]["removed"]),
                "locked": jid in task_ballots,
                "scores": task_ballots.get(jid, []),
            }
            for jid in judge_ids
        ]

    state["players"] = [
        {**player_to_dict(row), "removed": bool(row["removed"])} for row in players
    ]
    state["tasks"] = [
        {
            **dict(row),
            "performers": performers_by_task.get(row["id"], []),
            "judges": judges_for(row),
        }
        for row in tasks
    ]
    state["groups"] = [{"id": b["id"], "name": b["name"]} for b in state["boards"]]
    state["adjustments"] = [dict(row) for row in adjustment_rows]
    return state


def build_state(audience: str, player_id: int | None = None, central: dict | None = None) -> dict:
    if audience == "central":
        return central or build_central_state()
    if audience == "admin":
        return build_admin_state(central)
    if audience == "player" and player_id is not None:
        return build_player_state(player_id, central)
    raise ValueError(f"Unknown audience: {audience}")