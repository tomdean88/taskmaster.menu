import pytest

PHOTO = ("selfie.jpg", b"fake-image-bytes", "image/jpeg")


def join(client, name="Sam", group_id="1", photo=PHOTO):
    return client.post(
        "/api/join", data={"name": name, "group_id": group_id}, files={"photo": photo}
    )


def test_default_groups_exist(client):
    assert client.get("/api/groups").json() == [
        {"id": 1, "name": "Group 1"},
        {"id": 2, "name": "Group 2"},
    ]


def test_join_returns_token_but_player_view_hides_it(client):
    res = join(client)
    assert res.status_code == 200
    body = res.json()
    assert len(body["token"]) > 30
    assert body["player"]["name"] == "Sam"
    assert "token" not in body["player"]


def test_name_is_trimmed(client):
    assert join(client, name="  Sam  ").json()["player"]["name"] == "Sam"


@pytest.mark.parametrize("name", ["   ", "x" * 25])
def test_bad_names_rejected(client, name):
    assert join(client, name=name).status_code == 400


def test_unknown_group_rejected(client):
    assert join(client, group_id="99").status_code == 400


def test_non_image_rejected(client):
    assert join(client, photo=("notes.pdf", b"%PDF", "application/pdf")).status_code == 400


def test_oversized_photo_rejected(client):
    big = ("big.jpg", b"0" * (5 * 1024 * 1024 + 1), "image/jpeg")
    assert join(client, photo=big).status_code == 400


def test_uploaded_filename_is_never_trusted(client):
    url = join(client, photo=("../../evil.jpg", b"fake", "image/jpeg")).json()["player"]["photo_url"]
    assert "evil" not in url and ".." not in url
    assert url.startswith("/photos/") and url.endswith(".jpg")


def test_me_finds_player_by_token(client):
    body = join(client).json()
    res = client.get("/api/me", headers={"X-Player-Token": body["token"]})
    assert res.status_code == 200
    assert res.json()["id"] == body["player"]["id"]


def test_me_rejects_unknown_token(client):
    assert client.get("/api/me", headers={"X-Player-Token": "made-up"}).status_code == 404


def test_removed_player_can_join_again(game):
    sam = game.join("Sam")
    game.update_player(sam, removed=True)
    assert game.client.get("/api/me", headers={"X-Player-Token": sam["token"]}).status_code == 404
    game.join("Sam")  # the QR code still works for a fresh account