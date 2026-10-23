import pytest


def adjust(game, player, points, reason=""):
    return game.post_admin(
        "/adjustments", {"player_id": player["id"], "points": points, "reason": reason}
    )


def test_award_adds_points(game, party):
    assert adjust(game, party.ana, 2, "Great hat").status_code == 200
    assert game.points()["Ana"] == 2


def test_penalty_subtracts_points(game, party):
    adjust(game, party.ana, -3, "Cheated")
    assert game.points()["Ana"] == -3


def test_adjustments_stack_with_task_points(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 1)])
    game.reveal(party.task)
    adjust(game, party.ana, 2)
    assert game.points()["Ana"] == 7


def test_zero_points_rejected(game, party):
    assert adjust(game, party.ana, 0).status_code == 400


@pytest.mark.parametrize("points", [21, -21])
def test_out_of_range_rejected(game, party, points):
    assert adjust(game, party.ana, points).status_code == 422


def test_reason_too_long_rejected(game, party):
    assert adjust(game, party.ana, 1, "x" * 81).status_code == 422


def test_unknown_player_rejected(game, party):
    stranger = {"id": 999}
    assert adjust(game, stranger, 1).status_code == 400


def test_removed_player_rejected(game, party):
    game.update_player(party.ana, removed=True)
    assert adjust(game, party.ana, 1).status_code == 400


def test_undo_removes_adjustment(game, party):
    adjustment_id = adjust(game, party.ana, 2).json()["id"]
    url = f"/api/admin/adjustments/{adjustment_id}"
    assert game.client.delete(url, headers=game.admin).status_code == 200
    assert game.points()["Ana"] == 0
    assert game.client.delete(url, headers=game.admin).status_code == 404  # already gone


def test_adjustments_require_admin(game, party):
    res = game.client.post("/api/admin/adjustments", json={"player_id": party.ana["id"], "points": 5})
    assert res.status_code == 401


def test_admin_sees_adjustments_newest_first(game, party):
    adjust(game, party.ana, 2, "Great hat")
    adjust(game, party.ben, -1, "Late")
    adjustments = game.admin_state()["adjustments"]
    assert [(a["player_name"], a["points"], a["reason"]) for a in adjustments] == [
        ("Ben", -1, "Late"),
        ("Ana", 2, "Great hat"),
    ]


def test_player_sees_their_adjustment_total(game, party):
    adjust(game, party.ana, 2)
    adjust(game, party.ana, 1)
    assert game.player_state(party.ana)["bonus"] == 3