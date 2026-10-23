import pytest
from starlette.websockets import WebSocketDisconnect

from app import admin


def test_login_wrong_password(client):
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401


def test_login_fails_closed_without_password(client, monkeypatch):
    monkeypatch.setattr(admin, "ADMIN_PASSWORD", "")
    assert client.post("/api/admin/login", json={"password": ""}).status_code == 401


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "made-up"}])
def test_protected_routes_require_login(client, headers):
    res = client.put("/api/admin/tv-mode", json={"mode": "game"}, headers=headers)
    assert res.status_code == 401


def test_bad_admin_socket_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/admin") as ws:
            ws.send_json({"token": "made-up"})
            ws.receive_json()
    assert exc.value.code == 4401


def test_tv_mode_switch(game):
    res = game.client.put("/api/admin/tv-mode", json={"mode": "game"}, headers=game.admin)
    assert res.status_code == 200
    assert game.central()["mode"] == "game"


def test_tv_mode_rejects_unknown_value(game):
    res = game.client.put("/api/admin/tv-mode", json={"mode": "party"}, headers=game.admin)
    assert res.status_code == 422


def test_rename_group_shows_on_tv(game):
    game.client.patch("/api/admin/groups/1", json={"name": "Team Jordan"}, headers=game.admin)
    assert game.central()["boards"][0]["name"] == "Team Jordan"


def test_blank_group_name_rejected(game):
    res = game.client.patch("/api/admin/groups/1", json={"name": "   "}, headers=game.admin)
    assert res.status_code == 400


def test_move_player_between_groups(game):
    sam = game.join("Sam", group_id=1)
    game.update_player(sam, group_id=2)
    boards = game.central()["boards"]
    assert [p["name"] for p in boards[1]["players"]] == ["Sam"]


def test_player_update_is_all_or_nothing(game):
    sam = game.join("Sam")
    assert game.update_player(sam, name="Samwise", group_id=99).status_code == 400
    me = game.client.get("/api/me", headers={"X-Player-Token": sam["token"]}).json()
    assert me["name"] == "Sam"  # the rename was rolled back along with the bad group


def test_removed_player_leaves_and_returns_to_the_tv(game):
    sam = game.join("Sam")
    game.update_player(sam, removed=True)
    assert game.central()["joined_order"] == []
    game.update_player(sam, removed=False)
    assert len(game.central()["joined_order"]) == 1


def test_group_task_needs_a_group(game):
    assert game.post_admin("/tasks", {"title": "Hat", "stage": "group"}).status_code == 400


def test_task_order_and_moving(game):
    game.create_task("A")
    game.create_task("B")
    c = game.create_task("C")
    game.post_admin(f"/tasks/{c}/move", {"direction": "up"})
    assert [t["title"] for t in game.admin_state()["tasks"]] == ["A", "C", "B"]


def test_completed_tasks_are_skipped_when_moving(game):
    game.join("Ana", 1)
    game.join("Xia", 2)
    done = game.create_task("Done")
    next_up = game.create_task("Next")
    game.start(done)
    game.reveal(done)
    game.post_admin(f"/tasks/{next_up}/move", {"direction": "up"})  # nothing upcoming above it
    assert [t["title"] for t in game.admin_state()["tasks"]] == ["Done", "Next"]
    assert game.post_admin(f"/tasks/{done}/move", {"direction": "down"}).status_code == 400