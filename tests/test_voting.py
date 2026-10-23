import pytest


# ---------- Starting tasks ----------

def test_start_snapshots_performers_and_switches_tv(game, party):
    assert game.start(party.task).status_code == 200
    central = game.central()
    assert central["mode"] == "game"
    assert central["current_task"]["title"] == "Paper hat"
    performers = game.admin_state()["tasks"][0]["performers"]
    assert {p["name"] for p in performers} == {"Ana", "Ben"}


def test_roles(game, party):
    game.start(party.task)
    assert game.player_state(party.ana)["task"]["role"] == "performer"
    assert game.player_state(party.xia)["task"]["role"] == "judge"


def test_late_joiner_is_not_a_performer(game, party):
    game.start(party.task)
    cal = game.join("Cal", 1)
    assert game.player_state(cal)["task"]["role"] == "spectator"


def test_only_one_task_at_a_time(game, party):
    second = game.create_task("Egg", group_id=1)
    game.start(party.task)
    assert game.start(second).status_code == 400


def test_cannot_start_with_empty_group(game):
    task = game.create_task("Lonely", group_id=2)
    assert game.start(task).status_code == 400


# ---------- A full round ----------

def test_full_round_scores(game, party):
    game.start(party.task)
    assert game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)]).status_code == 200
    assert game.vote(party.yan, party.task, [(party.ana, 4), (party.ben, 3)]).status_code == 200
    assert game.points() == {"Ana": 0, "Ben": 0, "Xia": 0, "Yan": 0}  # hidden until reveal
    game.reveal(party.task)
    assert game.points() == {"Ana": 5, "Ben": 1, "Xia": 0, "Yan": 0}


def test_vote_count_on_tv(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    task = game.central()["current_task"]
    assert (task["locked_count"], task["judge_count"]) == (1, 2)


def test_points_add_up_across_tasks(game, party):
    second = game.create_task("Egg", group_id=1)
    for task in (party.task, second):
        game.start(task)
        game.vote(party.xia, task, [(party.ana, 5), (party.ben, 1)])
        game.reveal(task)
    points = game.points()
    assert (points["Ana"], points["Ben"]) == (10, 2)


def test_trimming_applies_through_the_api(game):
    ana = game.join("Ana", 1)
    ben = game.join("Ben", 1)
    judges = [game.join(f"Judge{n}", 2) for n in range(5)]
    task = game.create_task("Hat", 1)
    game.start(task)
    game.vote(judges[0], task, [(ana, 1), (ben, 5)])  # one judge tries to bury Ana
    for judge in judges[1:]:
        game.vote(judge, task, [(ana, 4), (ben, 3)])
    game.reveal(task)
    points = game.points()
    # Untrimmed, both total 17 and tie. Trimmed, Ana wins 12 to 9.
    assert (points["Ana"], points["Ben"]) == (5, 1)


# ---------- Ballot rules ----------

def test_performer_cannot_vote(game, party):
    game.start(party.task)
    assert game.vote(party.ana, party.task, [(party.ana, 5), (party.ben, 1)]).status_code == 403


def test_must_score_every_performer(game, party):
    game.start(party.task)
    assert game.vote(party.xia, party.task, [(party.ana, 5)]).status_code == 400


def test_cannot_score_a_non_performer(game, party):
    game.start(party.task)
    res = game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 5), (party.yan, 5)])
    assert res.status_code == 400


def test_duplicate_scores_rejected(game, party):
    game.start(party.task)
    res = game.vote(party.xia, party.task, [(party.ana, 5), (party.ana, 1), (party.ben, 3)])
    assert res.status_code == 400


@pytest.mark.parametrize("stars", [0, 6])
def test_stars_must_be_one_to_five(game, party, stars):
    game.start(party.task)
    assert game.vote(party.xia, party.task, [(party.ana, stars), (party.ben, 3)]).status_code == 422


def test_stale_ballot_rejected(game, party):
    game.start(party.task)
    game.reveal(party.task)
    assert game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)]).status_code == 400


def test_unknown_token_rejected(game, party):
    game.start(party.task)
    stranger = {"token": "made-up"}
    assert game.vote(stranger, party.task, [(party.ana, 5), (party.ben, 1)]).status_code == 401


def test_removed_judge_cannot_vote(game, party):
    game.start(party.task)
    game.update_player(party.xia, removed=True)
    assert game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)]).status_code == 401


def test_relocking_replaces_the_ballot(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.vote(party.xia, party.task, [(party.ana, 1), (party.ben, 5)])
    task = game.player_state(party.xia)["task"]
    assert task["locked"] is True
    # JSON object keys are always strings, so ids come back as "1", "2".
    assert task["my_scores"] == {str(party.ana["id"]): 1, str(party.ben["id"]): 5}


# ---------- DQ, sat out, removed ----------

def test_dq_scores_zero_and_leaves_the_ranking(game, party):
    game.start(party.task)
    game.set_performer(party.task, party.ana, "dq")
    game.vote(party.xia, party.task, [(party.ben, 2)])  # DQ'd performers aren't on the ballot
    game.reveal(party.task)
    points = game.points()
    assert (points["Ana"], points["Ben"]) == (0, 5)


def test_sat_out_gets_no_points(game, party):
    game.start(party.task)
    game.set_performer(party.task, party.ana, "sat_out")
    game.vote(party.xia, party.task, [(party.ben, 2)])
    game.reveal(party.task)
    points = game.points()
    assert (points["Ana"], points["Ben"]) == (0, 5)


def test_removed_judges_scores_are_ignored(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.vote(party.yan, party.task, [(party.ana, 1), (party.ben, 2)])
    game.reveal(party.task)
    assert game.points()["Ana"] == 5  # 6 to 3
    game.update_player(party.xia, removed=True)
    assert game.points()["Ben"] == 5  # only Yan counts now: 2 to 1


# ---------- Reopen, back to queue, cancel, delete ----------

def test_reopen_hides_points_until_revealed_again(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.reveal(party.task)
    assert game.points()["Ana"] == 5
    game.post_admin(f"/tasks/{party.task}/reopen")
    assert game.points()["Ana"] == 0
    game.reveal(party.task)
    assert game.points()["Ana"] == 5


def test_back_to_queue_clears_everything(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.reveal(party.task)
    assert game.post_admin(f"/tasks/{party.task}/reset").status_code == 200
    assert game.points()["Ana"] == 0
    task = game.admin_state()["tasks"][0]
    assert task["status"] == "draft"
    assert task["performers"] == []
    cal = game.join("Cal", 1)
    game.start(party.task)  # a fresh snapshot picks up the newcomer
    assert game.player_state(cal)["task"]["role"] == "performer"


def test_cancel_active_task(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    assert game.post_admin(f"/tasks/{party.task}/reset").status_code == 200
    assert game.central()["current_task"] is None
    assert game.player_state(party.xia)["task"] is None


def test_cannot_reset_a_draft(game, party):
    assert game.post_admin(f"/tasks/{party.task}/reset").status_code == 400


def test_cannot_delete_an_active_task(game, party):
    game.start(party.task)
    assert game.client.delete(f"/api/admin/tasks/{party.task}", headers=game.admin).status_code == 400


def test_deleting_a_completed_task_removes_its_points(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.reveal(party.task)
    assert game.points()["Ana"] == 5
    assert game.client.delete(f"/api/admin/tasks/{party.task}", headers=game.admin).status_code == 200
    assert game.points()["Ana"] == 0