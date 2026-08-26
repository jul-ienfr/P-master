"""Tests Phase 2 — resserrement bayésien des ranges et données ICM."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.range_updater import BayesianRangeUpdater, combo_strength  # noqa: E402
from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState  # noqa: E402


def test_combo_strength_classes():
    assert combo_strength("AA") == "strong"
    assert combo_strength("AKs") == "strong"
    assert combo_strength("72o") == "weak"
    assert combo_strength("TT") == "strong"
    assert combo_strength("T9o") == "medium"


def test_aggressive_action_tightens_range():
    updater = BayesianRangeUpdater()
    base = "AA, KK, 72o, 83o, AKs"
    tightened = updater.update(base, [{"player": "V", "action": "RAISE"}])

    kept = {item.strip() for item in tightened.split(",")}
    assert "72o" not in kept and "83o" not in kept
    assert "AA" in kept and "AKs" in kept


def test_fold_and_check_behaviour():
    updater = BayesianRangeUpdater()
    base = "AA, 72o"

    # FOLD : pas de mise à jour (le joueur a abandonné)
    assert updater.update(base, [{"action": "FOLD"}]) == ", ".join(
        ["AA", "72o"]
    )
    # CHECK faible-passif : les mains fortes perdent un peu de poids mais restent.
    checked = updater.update(base, [{"action": "CHECK"}])
    assert set(checked.split(", ")) == {"AA", "72o"}


def test_never_returns_empty_range():
    updater = BayesianRangeUpdater(min_weight=10.0)  # tout supprime a priori
    result = updater.update("AA, KK", [{"action": "RAISE"}])
    assert result.strip() != ""


def test_street_and_board_tightening():
    updater = BayesianRangeUpdater()
    base = "AA, T9o, 76s, 72o"
    loose = updater.update(base, [{"action": "CALL"}], street=0)
    tight = updater.update(base, [{"action": "CALL"}], street=2, board_texture="DRY")
    assert len(tight.split(",")) <= len(loose.split(","))


class _FakeController:
    def __init__(self, config):
        self.config = config


def _state(players):
    return CanonicalTableState(
        spot_id="spot-icm",
        street="TURN",
        pot=100.0,
        board=("Ah",),
        hero_cards=("As",),
        players=tuple(players),
    )


def test_build_tournament_data_disabled_in_cash_game():
    from src.bot.gate_flow import GateFlowMixin

    controller = _FakeController({"tournament": {"enabled": False}})
    controller._build_tournament_data = GateFlowMixin._build_tournament_data.__get__(controller)

    players = [
        CanonicalPlayer(seat_id="s0", seat_index=0, stack=3000.0, name="Hero", is_hero=True),
        CanonicalPlayer(seat_id="s1", seat_index=1, stack=2500.0, name="Villain"),
    ]
    assert controller._build_tournament_data(_state(players)) is None


def test_build_tournament_data_populated_when_enabled():
    from src.bot.gate_flow import GateFlowMixin

    controller = _FakeController({"tournament": {"enabled": True, "payouts": [100, 60, 40]}})
    controller._build_tournament_data = GateFlowMixin._build_tournament_data.__get__(controller)

    players = [
        CanonicalPlayer(seat_id="s0", seat_index=0, stack=3000.0, name="Hero", is_hero=True),
        CanonicalPlayer(seat_id="s1", seat_index=1, stack=2500.0, name="Villain"),
        CanonicalPlayer(seat_id="s2", seat_index=2, stack=1000.0, name="Short", is_active=False),
    ]
    data = controller._build_tournament_data(_state(players))

    assert data is not None
    assert data["hero_stack"] == 3000.0
    assert data["villain_stack"] == 2500.0
    assert data["all_stacks"] == [3000.0, 2500.0]
    assert data["payouts"] == [100.0, 60.0, 40.0]


def test_build_tournament_data_requires_two_payouts():
    from src.bot.gate_flow import GateFlowMixin

    controller = _FakeController({"tournament": {"enabled": True, "payouts": [100]}})
    controller._build_tournament_data = GateFlowMixin._build_tournament_data.__get__(controller)
    players = [
        CanonicalPlayer(seat_id="s0", seat_index=0, stack=3000.0, name="Hero", is_hero=True),
    ]
    assert controller._build_tournament_data(_state(players)) is None


def test_count_active_villains():
    from src.bot.gate_flow import GateFlowMixin

    count = GateFlowMixin._count_active_villains

    hu_state = _state(
        [
            CanonicalPlayer(seat_id="s0", seat_index=0, stack=100.0, name="Hero", is_hero=True),
            CanonicalPlayer(seat_id="s1", seat_index=1, stack=100.0, name="V"),
        ]
    )
    assert count(hu_state) == 2

    three_way = _state(
        [
            CanonicalPlayer(seat_id="s0", seat_index=0, stack=100.0, name="Hero", is_hero=True),
            CanonicalPlayer(seat_id="s1", seat_index=1, stack=100.0, name="V1"),
            CanonicalPlayer(seat_id="s2", seat_index=2, stack=80.0, name="V2"),
            CanonicalPlayer(seat_id="s3", seat_index=3, stack=60.0, name="Folded", has_folded=True),
        ]
    )
    assert count(three_way) == 3
