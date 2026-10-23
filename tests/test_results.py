import json


def reset_ballot(game, task_id, judge):
    return game.client.delete(
        f"/api/admin/tasks/{task_id}/ballots/{judge['id']}", headers=game.admin
    )


# ---------- Results on the TV ----------

def test_no_results_before_any_reveal(game, party):
    assert game.central()["last_result"] is None


def test_reveal_shows_results_on_tv(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    game.vote(party.yan, party.task, [(party.ana, 4), (party.ben, 3)])
    game.reveal(party.task)
    central = game.central()
    assert central["mode"] == "results"
    result = central["last_result"]
    assert result["title"] == "Paper hat"
    assert [(r["name"], r["total"], r["points"]) for r in result["rows"]] == [
        ("Ana", 9, 5),
        ("Ben", 5, 1),
    ]


def test_results_show_disqualified_performers(game, party):
    game.start(party.task)
    game.set_performer(party.task, party.ana, "dq")
    game.vote(party.xia, party.task, [(party.ben, 3)])
    game.reveal(party.task)
    rows = {r["name"]: r for r in game.central()["last_result"]["rows"]}
    assert rows["Ana"]["status"] == "dq"
    assert rows["Ana"]["total"] is None
    assert rows["Ana"]["points"] == 0
    assert rows["Ben"]["points"] == 5


def test_results_screen_has_no_individual_stars(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    game.reveal(party.task)
    assert "stars" not in json.dumps(game.central())


def test_starting_next_task_returns_tv_to_game(game, party):
    second = game.create_task("Egg", group_id=1)
    game.start(party.task)
    game.reveal(party.task)
    assert game.central()["mode"] == "results"
    game.start(second)
    assert game.central()["mode"] == "game"


def test_admin_can_choose_results_mode(game):
    res = game.client.put("/api/admin/tv-mode", json={"mode": "results"}, headers=game.admin)
    assert res.status_code == 200
    assert game.central()["mode"] == "results"


# ---------- Ballot audit ----------

def test_draft_tasks_have_no_judges(game, party):
    assert game.admin_state()["tasks"][0]["judges"] == []


def test_admin_sees_every_ballot(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    judges = game.admin_state()["tasks"][0]["judges"]
    assert [(j["name"], j["locked"]) for j in judges] == [("Xia", True), ("Yan", False)]
    assert judges[0]["scores"] == [
        {"performer": "Ana", "stars": 5},
        {"performer": "Ben", "stars": 2},
    ]


def test_moved_judge_still_appears_in_audit(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    game.update_player(party.xia, group_id=1)  # moved after voting
    names = [j["name"] for j in game.admin_state()["tasks"][0]["judges"]]
    assert "Xia" in names


# ---------- Reset ballot ----------

def test_reset_ballot_lets_judge_vote_again(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    assert reset_ballot(game, party.task, party.xia).status_code == 200
    assert game.player_state(party.xia)["task"]["locked"] is False
    assert game.vote(party.xia, party.task, [(party.ana, 1), (party.ben, 1)]).status_code == 200


def test_reset_without_a_ballot_is_404(game, party):
    game.start(party.task)
    assert reset_ballot(game, party.task, party.xia).status_code == 404


def test_reset_after_reveal_recalculates_points(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.vote(party.yan, party.task, [(party.ana, 1), (party.ben, 2)])
    game.reveal(party.task)
    assert game.points()["Ana"] == 5  # 6 to 3
    reset_ballot(game, party.task, party.xia)
    assert game.points()["Ben"] == 5  # only Yan counts now: 2 to 1


def test_reset_ballot_requires_admin(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    res = game.client.delete(f"/api/admin/tasks/{party.task}/ballots/{party.xia['id']}")
    assert res.status_code == 401