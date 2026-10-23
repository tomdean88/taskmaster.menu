"""Shared test fixtures. pytest loads this file automatically."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import admin, db, join
from app.main import app

TEST_PASSWORD = "test-password"
FAKE_PHOTO = ("selfie.jpg", b"not-really-a-jpeg", "image/jpeg")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh app with its own throwaway database for every single test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(join, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(admin, "ADMIN_PASSWORD", TEST_PASSWORD)
    monkeypatch.setattr(admin, "LOGIN_FAIL_DELAY", 0)
    with TestClient(app) as test_client:  # "with" runs the lifespan, which runs init_db
        yield test_client


@pytest.fixture
def admin_headers(client):
    res = client.post("/api/admin/login", json={"password": TEST_PASSWORD})
    assert res.status_code == 200
    return {"X-Admin-Token": res.json()["token"]}


class Game:
    """Small helpers so each test reads like a story about the party."""

    def __init__(self, client, admin_headers):
        self.client = client
        self.admin = admin_headers
        self.admin_token = admin_headers["X-Admin-Token"]

    # ----- players -----

    def join(self, name, group_id=1):
        res = self.client.post(
            "/api/join",
            data={"name": name, "group_id": str(group_id)},
            files={"photo": FAKE_PHOTO},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        return {"id": body["player"]["id"], "token": body["token"], "name": name}

    def update_player(self, player, **changes):
        return self.client.patch(
            f"/api/admin/players/{player['id']}", json=changes, headers=self.admin
        )

    # ----- tasks -----

    def post_admin(self, path, json=None):
        return self.client.post(f"/api/admin{path}", json=json, headers=self.admin)

    def create_task(self, title="Task", group_id=1, stage="group"):
        payload = {"title": title, "stage": stage}
        if stage == "group":
            payload["group_id"] = group_id
        res = self.post_admin("/tasks", payload)
        assert res.status_code == 200, res.text
        return res.json()["id"]

    def start(self, task_id):
        return self.post_admin(f"/tasks/{task_id}/start")

    def reveal(self, task_id):
        return self.post_admin(f"/tasks/{task_id}/reveal")

    def set_performer(self, task_id, player, status):
        return self.client.patch(
            f"/api/admin/tasks/{task_id}/performers/{player['id']}",
            json={"status": status},
            headers=self.admin,
        )

    def vote(self, judge, task_id, scores):
        """scores is a list of (performer, stars) pairs."""
        return self.client.post(
            "/api/ballot",
            json={
                "task_id": task_id,
                "scores": [{"performer_id": p["id"], "stars": s} for p, s in scores],
            },
            headers={"X-Player-Token": judge["token"]},
        )

    # ----- snapshots, exactly as each screen receives them -----

    def central(self):
        with self.client.websocket_connect("/ws/central") as ws:
            return ws.receive_json()

    def admin_state(self):
        with self.client.websocket_connect("/ws/admin") as ws:
            ws.send_json({"token": self.admin_token})
            return ws.receive_json()

    def player_state(self, player):
        with self.client.websocket_connect("/ws/player") as ws:
            ws.send_json({"token": player["token"]})
            return ws.receive_json()

    def points(self):
        """Leaderboard points by player name, as the TV shows them."""
        return {
            p["name"]: p["points"]
            for board in self.central()["boards"]
            for p in board["players"]
        }


@pytest.fixture
def game(client, admin_headers):
    return Game(client, admin_headers)


@pytest.fixture
def party(game):
    """Ana and Ben perform (group 1), Xia and Yan judge (group 2), with one group 1 task."""
    return SimpleNamespace(
        ana=game.join("Ana", 1),
        ben=game.join("Ben", 1),
        xia=game.join("Xia", 2),
        yan=game.join("Yan", 2),
        task=game.create_task("Paper hat", group_id=1),
    )