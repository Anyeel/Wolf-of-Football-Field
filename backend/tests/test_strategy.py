import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from strategy import StrategyEngine


@pytest.fixture
def engine():
    return StrategyEngine()


def test_calculate_attractiveness_score(engine):
    player = {
        'average_points': 5,
        'streak': ['good', 'good', 'fair'],
    }
    # base = 5 * 5 = 25; streak = 8 + 8 + 2 = 18; total = 43
    assert engine._calculate_attractiveness_score(player) == 43


def test_optimize_lineup_picks_best_formation(engine):
    # Unbalanced squad: great forwards, few defenders -> 3-4-3 fits exactly.
    squad = [{'id': 1, 'position': 'GK', 'average_points': 5, 'streak': []}]
    squad += [{'id': 10 + i, 'position': 'DF', 'average_points': 3, 'streak': []} for i in range(3)]
    squad += [{'id': 20 + i, 'position': 'MF', 'average_points': 5, 'streak': []} for i in range(4)]
    squad += [{'id': 30 + i, 'position': 'FW', 'average_points': 9, 'streak': []} for i in range(3)]

    result = engine.optimize_lineup(squad)

    assert result['formation'] == '3-4-3'
    assert len(result['slots']) == 11
    # Captain must be a forward (highest average in the squad).
    assert result['slots'][result['captain_slot']] >= 30


def test_optimize_lineup_fields_injured_over_empty_slot(engine):
    squad = [
        {'id': i,
         'position': 'GK' if i == 0 else 'DF' if i < 5 else 'MF' if i < 9 else 'FW',
         'average_points': 5, 'streak': []}
        for i in range(11)
    ]
    squad[1]['status'] = 'injured'

    result = engine.optimize_lineup(squad)

    # An injured player (0 pts) still beats an empty slot (-4 pts).
    assert len(result['slots']) == 11
    assert 1 in result['slots'].values()


def test_market_suggestions_ranked_and_priced(engine):
    market = [
        {'id': 1, 'name': 'Player 1', 'value': 200000, 'average_points': 6, 'streak': ['good']},
        {'id': 2, 'name': 'Player 2', 'value': 100000, 'average_points': 2, 'streak': []},
    ]

    suggestions = engine.get_market_suggestions(market)

    assert len(suggestions) == 2
    assert suggestions[0]['player_id'] == 1  # Ordered by score, best first
    assert suggestions[0]['suggested_bid'] == int(200000 * 1.05)
    assert suggestions[1]['suggested_bid'] == engine.MIN_PRICE_BID


def test_clausulazo_accepts_fair_clause(engine):
    # 140% of market value, 14% of balance: both within limits.
    ok, reason = engine.evaluate_clausulazo(
        market_value=1_000_000, clause_value=1_400_000, balance=10_000_000
    )
    assert ok, reason


def test_clausulazo_rejects_excessive_premium(engine):
    # 200% of market value exceeds the 150% premium cap.
    ok, reason = engine.evaluate_clausulazo(
        market_value=1_000_000, clause_value=2_000_000, balance=100_000_000
    )
    assert not ok
    assert 'market value' in reason


def test_clausulazo_rejects_balance_drain(engine):
    # The clause is fair vs market value but eats 80% of the balance.
    ok, reason = engine.evaluate_clausulazo(
        market_value=1_000_000, clause_value=1_200_000, balance=1_500_000
    )
    assert not ok
    assert 'balance' in reason


def test_clausulazo_rejects_missing_data(engine):
    ok, _ = engine.evaluate_clausulazo(market_value=0, clause_value=0, balance=1_000_000)
    assert not ok
