import asyncio
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _StubMachine:
    def __init__(self, model, states, initial):
        self.model = model
        self.states = list(states)
        model.state = initial

    def add_transition(self, trigger, source, dest):
        def transition_method():
            self.model.state = dest

        setattr(self.model, trigger, transition_method)


if "transitions" not in sys.modules:
    sys.modules["transitions"] = types.SimpleNamespace(Machine=_StubMachine)


from src.bot.table_tracker import TableTracker


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class StubDB:
    def __init__(self):
        self.observed_calls = []
        self.action_updates = []
        self.hand_history_calls = []

    async def record_observed_hand(self, player_name: str, street: str = "UNKNOWN"):
        self.observed_calls.append((player_name, street))

    async def update_player_action(self, player_name: str, action_data: dict):
        self.action_updates.append((player_name, action_data))

    async def insert_hand_history(self, table_name: str, board: list, actions: list):
        self.hand_history_calls.append((table_name, list(board), list(actions)))


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _player_snapshot(player) -> dict:
    return {
        "seat_id": player.seat_id,
        "seat_index": player.seat_index,
        "name": player.name,
        "starting_stack": player.starting_stack,
        "current_stack": player.current_stack,
        "bet": player.bet,
        "is_active": player.is_active,
        "has_folded": player.has_folded,
        "is_hero": player.is_hero,
        "has_button": player.has_button,
    }


def _tracker_snapshot(tracker: TableTracker) -> dict:
    return {
        "state": tracker.state,
        "current_board": list(tracker.current_board),
        "pot_total": tracker.pot_total,
        "last_pot": tracker.last_pot,
        "hero_cards": list(tracker.hero_cards),
        "legal_actions": list(tracker.legal_actions),
        "action_buttons": list(tracker.action_buttons),
        "spot_id": tracker.spot_id,
        "state_confidence": tracker.state_confidence,
        "current_hand_actions": list(tracker.current_hand_actions),
        "observed_players_this_hand": sorted(tracker.observed_players_this_hand),
        "players": [
            _player_snapshot(tracker.players[seat_id])
            for seat_id in sorted(tracker.players)
        ],
    }


def _db_snapshot(db: StubDB) -> dict:
    return {
        "observed_calls": [list(call) for call in db.observed_calls],
        "action_updates": [[name, data] for name, data in db.action_updates],
        "hand_history_calls": [
            [table_name, board, actions]
            for table_name, board, actions in db.hand_history_calls
        ],
    }


def _run_replay(fixture_name: str) -> dict:
    fixture = _load_fixture(fixture_name)
    db = StubDB()
    tracker = TableTracker(db)

    async def scenario():
        for frame in fixture["frames"]:
            await tracker.update_from_vision(frame)

    asyncio.run(scenario())
    return {
        "tracker": _tracker_snapshot(tracker),
        "db": _db_snapshot(db),
    }


def test_table_tracker_street_progression_replay_matches_expected_snapshot():
    fixture = _load_fixture("table_tracker_replay_street_progression.json")

    assert _run_replay("table_tracker_replay_street_progression.json") == fixture["expected"]


def test_table_tracker_new_hand_reset_replay_matches_expected_snapshot():
    fixture = _load_fixture("table_tracker_replay_new_hand_reset.json")

    assert _run_replay("table_tracker_replay_new_hand_reset.json") == fixture["expected"]
