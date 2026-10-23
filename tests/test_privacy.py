import json

import pytest
from starlette.websockets import WebSocketDisconnect


def everyone(party):
    return (party.ana, party.ben, party.xia, party.yan)


def test_tv_snapshot_has_no_tokens_or_stars(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    text = json.dumps(game.central())
    for player in everyone(party):
        assert player["token"] not in text
    assert "stars" not in text
    assert "my_scores" not in text


def test_admin_snapshot_has_no_tokens(game, party):
    text = json.dumps(game.admin_state())
    for player in everyone(party):
        assert player["token"] not in text
    assert game.admin_token not in text


def test_player_snapshot_has_no_other_tokens(game, party):
    text = json.dumps(game.player_state(party.xia))
    for player in (party.ana, party.ben, party.yan):
        assert player["token"] not in text


def test_players_only_see_their_own_ballot(game, party):
    game.start(party.task)
    game.vote(party.xia, party.task, [(party.ana, 5), (party.ben, 2)])
    yan = game.player_state(party.yan)["task"]
    assert yan["my_scores"] == {}
    assert yan["locked"] is False
    ana = game.player_state(party.ana)["task"]  # a performer sees no ballot at all
    assert ana["my_scores"] == {}
    assert ana["performers"] == []


def test_up_next_never_reveals_the_task_title(game, party):
    central = game.central()
    assert central["up_next"]["group_id"] == 1
    assert "Paper hat" not in json.dumps(central)
    assert "Paper hat" not in json.dumps(game.player_state(party.xia))


def test_bad_player_socket_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/player") as ws:
            ws.send_json({"token": "made-up"})
            ws.receive_json()
    assert exc.value.code == 4401


def test_removed_player_snapshot_is_empty(game, party):
    game.update_player(party.ana, removed=True)
    assert game.player_state(party.ana) == {"audience": "player", "me": None}