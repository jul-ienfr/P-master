import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.gate_flow import GateFlowMixin
from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState


class FakePreflopManager:
    def get_villain_range(self, position):
        return f"range:{position}"


class Controller(GateFlowMixin):
    def __init__(self):
        self.tracker = SimpleNamespace(players={})
        self.decision_maker = SimpleNamespace(preflop_manager=FakePreflopManager())


def make_state(players):
    return CanonicalTableState(
        spot_id="spot-1",
        street="FLOP",
        pot=20.0,
        board=("2c", "7d", "Jh"),
        hero_cards=("Ah", "Kd"),
        players=tuple(players),
        legal_actions=("CHECK", "BET"),
    )


def test_count_active_villains_ignores_sitout_and_folded_players():
    state = make_state(
        [
            CanonicalPlayer(seat_id="p1", name="Hero", is_hero=True),
            CanonicalPlayer(seat_id="p2", name="V1", is_active=True),
            CanonicalPlayer(seat_id="p3", name="Sitout", is_active=False),
            CanonicalPlayer(seat_id="p4", name="Folded", is_active=True, has_folded=True),
            CanonicalPlayer(seat_id="p5", name="V2", is_active=True),
        ]
    )

    assert GateFlowMixin._count_active_villains(state) == 3


def test_build_multiway_context_orders_players_by_engine_position():
    controller = Controller()
    controller.tracker.players = {
        "p1": SimpleNamespace(position="CO", is_active=True, has_folded=False),
        "p2": SimpleNamespace(position="SB", is_active=True, has_folded=False),
        "p3": SimpleNamespace(position="BTN", is_active=True, has_folded=False),
        "p4": SimpleNamespace(position="BB", is_active=True, has_folded=False),
    }
    state = make_state(
        [
            CanonicalPlayer(seat_id="p1", name="V1", is_active=True),
            CanonicalPlayer(seat_id="p2", name="V2", is_active=True),
            CanonicalPlayer(seat_id="p3", name="Hero", is_hero=True, is_active=True),
            CanonicalPlayer(seat_id="p4", name="V3", is_active=True),
            CanonicalPlayer(seat_id="p5", name="Sitout", is_active=False),
        ]
    )
    primary = SimpleNamespace(name="V2", seat_id="p2", has_button=False)

    context = controller._build_multiway_context(state, primary)

    assert context is not None
    assert context.num_players == 4
    assert context.hero_player_index == 2
    assert context.active_positions == ("SB", "CO", "BTN", "BB")
    assert context.villain_ranges == ("range:SB", "range:CO", "range:BB")
    assert context.primary_villain_index == 0
