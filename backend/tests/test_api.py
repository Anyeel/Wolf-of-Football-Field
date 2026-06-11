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


def test_get_squad_details_enriches_from_json(api):
    """Club membership, purchase price, injuries and offers come from the
    player-community-info JSON, which is authoritative (the HTML rows are not)."""
    squad = [
        {'id': 1, 'name': 'Left League', 'status': 'ok'},
        {'id': 2, 'name': 'Listed With Offer', 'status': 'ok'},
    ]
    infos = {
        1: {"data": {"team": None, "transfer": {"price": None}, "injury": [],
                     "market": {"id": None, "price": 0}, "bid": {"isActive": 0}}},
        2: {"data": {"team": {"id": 9, "name": "Qatar"},
                     "transfer": {"price": 1_000_000}, "injury": ["knee"],
                     "market": {"id": 77, "price": 2_000_000},
                     "bid": {"isActive": 1, "amount": 1_500_000, "days": 2}}},
    }
    with patch.object(api, 'get_player_community_info', side_effect=lambda pid: infos[pid]):
        api.get_squad_details(squad)

    assert squad[0]['has_team'] is False           # Null team = left the league
    assert squad[1]['has_team'] is True
    assert squad[1]['purchase_price'] == 1_000_000
    assert squad[1]['status'] == 'injured'         # Mister's own injury report
    assert squad[1]['on_market'] is True
    assert squad[1]['offer']['amount'] == 1_500_000


def test_missing_env_vars():
    with patch.dict(os.environ, clear=True):
        from api import MisterAPI
        with pytest.raises(ValueError):
            MisterAPI()
