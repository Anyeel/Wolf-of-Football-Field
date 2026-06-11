import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def api():
    with patch.dict(os.environ, {"MISTER_AUTH_TOKEN": "test_token",
                                 "MISTER_COOKIE": "test_cookie"}):
        from api import MisterAPI
        return MisterAPI()


def test_get_market_parses_players(api):
    mock_resp = MagicMock()
    mock_resp.text = '''
        <div class="player-row">
            <div class="player-avatar" data-id_player="123"></div>
            <div class="name">Messi</div>
            <div class="player-position" data-position="4"></div>
            <div class="underName">1.000.000 €</div>
            <div class="points">100</div>
        </div>
    '''
    with patch.object(api.session, 'post', return_value=mock_resp):
        players = api.get_market()

    assert len(players) == 1
    assert players[0]['id'] == 123
    assert players[0]['name'] == 'Messi'
    assert players[0]['position'] == 'FW'
    assert players[0]['value'] == 1000000
    assert players[0]['points'] == 100


def test_set_captain_sends_json(api):
    mock_resp = MagicMock(status_code=200)
    with patch.object(api.session, 'post', return_value=mock_resp) as mock_post:
        assert api.set_captain(12345, 5) is True

    args, kwargs = mock_post.call_args
    assert "managers/12345/lineup/captain" in args[0]
    assert kwargs['headers']['content-type'] == 'application/json'
    assert kwargs['json'] == {"slot_index": 5}


def test_finances_fail_safe_returns_zero(api):
    """Without real balance data the API must report 0€, never made-up money."""
    mock_resp = MagicMock()
    mock_resp.text = ""
    mock_resp.json.side_effect = ValueError("not json")
    with patch.object(api.session, 'post', return_value=mock_resp):
        finances = api.get_user_finances()

    assert finances == {"balance": 0, "max_bid": 0}


def test_missing_env_vars():
    with patch.dict(os.environ, clear=True):
        from api import MisterAPI
        with pytest.raises(ValueError):
            MisterAPI()
