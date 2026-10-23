import pytest


def set_finalists(game, *players):
    return game.client.put(
        "/api/admin/finalists",
        json={"player_ids": [p["id"] for p in players]},
        headers=game.admin,
    )


@pytest.fixture
def final(game, party):
    """Ana (group 1) and Xia (group 2) are the finalists. Ben and Yan judge."""
    task = game.create_task("Grand final", stage="final")
    set_finalists(game, party.ana, party.xia)
    return task


def final_task(game):
    return next(t for t in game.admin_state()["tasks"] if t["stage"] == "final")


# ---------- Choosing finalists ----------

def test_final_needs_two_finalists(game, party):
    task = game.create_task("Grand final", stage="final")
    assert game.start(task).status_code == 400  # nobody picked yet
    set_finalists(game, party.ana)
    assert game.start(task).status_code == 400  # one isn't a contest


def test_finalists_must_be_active_players(game, party):
    game.update_player(party.ben, removed=True)
    assert set_finalists(game, party.ana, party.ben).status_code == 400
    assert set_finalists(game, party.ana, {"id": 999}).status_code == 400


def test_duplicate_finalists_collapse(game, party):
    set_finalists(game, party.ana, party.ana, party.xia)
    assert sorted(game.admin_state()["finalist_ids"]) == sorted([party.ana["id"], party.xia["id"]])


def test_finalists_require_admin(game, party):
    res = game.client.put("/api/admin/finalists", json={"player_ids": [party.ana["id"]]})
    assert res.status_code == 401


def test_no_champion_before_the_final_is_revealed(game, party, final):
    standings = game.central()["final"]
    assert standings["champion_ids"] == []
    assert {p["name"]: p["final_points"] for p in standings["finalists"]} == {"Ana": 0, "Xia": 0}


# ---------- Running the final ----------

def test_final_snapshots_finalists_as_performers(game, party, final):
    assert game.start(final).status_code == 200
    assert {p["name"] for p in final_task(game)["performers"]} == {"Ana", "Xia"}


def test_everyone_else_judges_the_final(game, party, final):
    game.start(final)
    assert game.player_state(party.ana)["task"]["role"] == "performer"
    assert game.player_state(party.xia)["task"]["role"] == "performer"
    assert game.player_state(party.ben)["task"]["role"] == "judge"
    assert game.player_state(party.yan)["task"]["role"] == "judge"


def test_final_vote_count_on_tv(game, party, final):
    game.start(final)
    game.vote(party.ben, final, [(party.ana, 5), (party.xia, 2)])
    task = game.central()["current_task"]
    assert task["stage"] == "final"
    assert (task["locked_count"], task["judge_count"]) == (1, 2)


def test_finalist_cannot_vote_in_the_final(game, party, final):
    game.start(final)
    assert game.vote(party.ana, final, [(party.ana, 5), (party.xia, 1)]).status_code == 403


def test_group_mate_can_judge_the_final(game, party, final):
    game.start(final)
    # Ben is in Ana's group, but in the final everyone who isn't performing judges.
    assert game.vote(party.ben, final, [(party.ana, 5), (party.xia, 2)]).status_code == 200


def test_admin_audit_lists_final_judges(game, party, final):
    game.start(final)
    assert [j["name"] for j in final_task(game)["judges"]] == ["Ben", "Yan"]


# ---------- Scoring the final ----------

def run_final(game, party, task, ana_stars, xia_stars):
    game.start(task)
    for judge in (party.ben, party.yan):
        game.vote(judge, task, [(party.ana, ana_stars), (party.xia, xia_stars)])
    game.reveal(task)


def test_final_points_never_touch_the_leaderboard(game, party, final):
    run_final(game, party, final, 5, 1)
    assert game.points() == {"Ana": 0, "Ben": 0, "Xia": 0, "Yan": 0}


def test_champion_is_crowned(game, party, final):
    run_final(game, party, final, 5, 1)
    standings = game.central()["final"]
    assert standings["champion_ids"] == [party.ana["id"]]
    assert [(p["name"], p["final_points"]) for p in standings["finalists"]] == [("Ana", 5), ("Xia", 1)]


def test_final_results_screen(game, party, final):
    run_final(game, party, final, 5, 1)
    result = game.central()["last_result"]
    assert result["stage"] == "final"
    assert result["title"] == "Grand final"


def test_tied_final_has_co_champions(game, party, final):
    run_final(game, party, final, 5, 5)
    champions = game.central()["final"]["champion_ids"]
    assert sorted(champions) == sorted([party.ana["id"], party.xia["id"]])


def test_tiebreak_task_decides_the_champion(game, party, final):
    run_final(game, party, final, 5, 5)  # tie: both get 5
    tiebreak = game.create_task("Tiebreak", stage="final")
    run_final(game, party, tiebreak, 5, 1)  # Ana 10, Xia 6
    assert game.central()["final"]["champion_ids"] == [party.ana["id"]]


def test_champion_tv_mode(game):
    res = game.client.put("/api/admin/tv-mode", json={"mode": "champion"}, headers=game.admin)
    assert res.status_code == 200
    assert game.central()["mode"] == "champion"