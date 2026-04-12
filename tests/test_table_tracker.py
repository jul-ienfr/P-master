import asyncio
import logging
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


def run(coro):
    return asyncio.run(coro)


def test_records_observed_hand_once_per_player_and_hand():
    db = StubDB()
    tracker = TableTracker(db)

    vision_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }

    run(tracker.update_from_vision(vision_state))
    run(tracker.update_from_vision(vision_state))

    assert db.observed_calls == [("Hero", "PREFLOP"), ("Villain", "PREFLOP")]
    assert tracker.state == "PREFLOP"


def test_reset_for_new_hand_allows_observed_hand_to_be_recorded_again():
    db = StubDB()
    tracker = TableTracker(db)

    first_hand = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }

    run(tracker.update_from_vision(first_hand))
    tracker.reset_for_new_hand()
    run(tracker.update_from_vision(first_hand))

    assert db.observed_calls == [("Villain", "PREFLOP"), ("Villain", "PREFLOP")]


def test_detected_fold_is_recorded_and_saved_when_new_hand_starts():
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "active": True},
        ],
    }
    fold_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "active": False, "folded": True},
        ],
    }
    new_hand_signal = {
        "street": "PREFLOP",
        "hero_cards": ["Qs", "Qc"],
        "board": [],
        "pot": 1.0,
        "state_confidence": 0.95,
        "players": [],
    }

    run(tracker.update_from_vision(opening_state))
    run(tracker.update_from_vision(fold_state))
    tracker.current_board = ["2c", "7d", "Jh"]
    run(tracker.update_from_vision(new_hand_signal))

    assert tracker.state == "PREFLOP"
    assert tracker.pending_board_reset == []
    assert tracker.pending_board_reset_frames == 1

    run(tracker.update_from_vision(new_hand_signal))

    assert len(db.action_updates) == 1
    player_name, action_data = db.action_updates[0]
    assert player_name == "Villain"
    assert action_data["action"] == "FOLD"
    assert action_data["street"] == "PREFLOP"

    assert len(db.hand_history_calls) == 1
    table_name, board, actions = db.hand_history_calls[0]
    assert table_name == "Table_1"
    assert board == ["2c", "7d", "Jh"]
    assert actions[0]["player"] == "Villain"
    assert actions[0]["action"] == "FOLD"
    assert tracker.state == "IDLE"
    assert tracker.current_hand_actions == []


def test_missing_seat_index_does_not_overwrite_known_player_seat():
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    missing_seat_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "hero", "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(opening_state))
    run(tracker.update_from_vision(missing_seat_frame))

    assert tracker.players["hero"].seat_index == 0


def test_valid_board_can_advance_street_when_street_hint_lags():
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    flop_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    delayed_street_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 5.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(opening_state))
    run(tracker.update_from_vision(flop_frame))
    run(tracker.update_from_vision(delayed_street_frame))

    assert tracker.state == "FLOP"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_street_promotion == "TURN"
    assert tracker.pending_street_promotion_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_street_promotion_frames == 1

    run(tracker.update_from_vision(delayed_street_frame))

    assert tracker.state == "TURN"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_street_promotion is None
    assert tracker.pending_street_promotion_board is None
    assert tracker.pending_street_promotion_frames == 0


def test_single_ambiguous_turn_promotion_waits_for_second_matching_frame():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    first_turn_candidate = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.8,
        "players": [],
    }
    recovery_flop_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.9,
        "players": [],
    }

    run(tracker.update_from_vision(first_turn_candidate))

    assert tracker.state == "FLOP"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_street_promotion == "TURN"
    assert tracker.pending_street_promotion_frames == 1

    run(tracker.update_from_vision(recovery_flop_frame))

    assert tracker.state == "FLOP"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_board_reset is None
    assert tracker.pending_board_reset_frames == 0
    assert tracker.pending_street_promotion is None
    assert tracker.pending_street_promotion_board is None
    assert tracker.pending_street_promotion_frames == 0


def test_low_pot_during_pending_turn_promotion_does_not_arm_new_hand_reset():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.pot_total = 8.0
    first_turn_candidate = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.8,
        "players": [],
    }
    noisy_turn_frame = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.7,
        "players": [],
    }

    run(tracker.update_from_vision(first_turn_candidate))
    run(tracker.update_from_vision(noisy_turn_frame))

    assert tracker.state == "TURN"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pot_total == 8.0
    assert tracker.pending_new_hand_pot is None
    assert tracker.pending_new_hand_frames == 0
    assert db.hand_history_calls == []


def test_pot_validation_uses_previous_verified_pot_without_false_ocr_warning(caplog):
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }
    flop_bet_state = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 5.5,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 96.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }
    turn_bet_state = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 6.0,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 96.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 97.0},
        ],
    }

    with caplog.at_level(logging.WARNING, logger="SanityChecker"):
        run(tracker.update_from_vision(opening_state))
        run(tracker.update_from_vision(flop_bet_state))
        run(tracker.update_from_vision(turn_bet_state))

    assert tracker.pot_total == 6.0
    assert tracker.last_pot == 5.5
    assert "Anomalie OCR bloquée" not in caplog.text


def test_pot_drop_requires_two_frames_before_new_hand_reset():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.pot_total = 8.0
    first_low_pot_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.7,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    second_low_pot_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.7,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(first_low_pot_frame))

    assert tracker.state == "FLOP"
    assert tracker.pot_total == 8.0
    assert tracker.pending_new_hand_pot == 1.5
    assert tracker.pending_new_hand_frames == 1
    assert db.hand_history_calls == []

    run(tracker.update_from_vision(second_low_pot_frame))

    assert tracker.state == "IDLE"
    assert tracker.pot_total == 0.0
    assert tracker.pending_new_hand_pot is None
    assert tracker.pending_new_hand_frames == 0


def test_board_drop_requires_two_frames_before_new_hand_reset():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "TURN"
    tracker.current_board = ["2c", "7d", "Jh", "Qs"]
    tracker.pot_total = 8.0
    first_board_drop_frame = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.7,
        "players": [],
    }
    second_board_drop_frame = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.7,
        "players": [],
    }

    run(tracker.update_from_vision(first_board_drop_frame))

    assert tracker.state == "TURN"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_board_reset == []
    assert tracker.pending_board_reset_frames == 1

    run(tracker.update_from_vision(second_board_drop_frame))

    assert tracker.state == "IDLE"
    assert tracker.current_board == []
    assert tracker.pending_board_reset is None
    assert tracker.pending_board_reset_frames == 0


def test_single_frame_board_drop_candidate_is_cleared_when_next_frame_recovers():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "TURN"
    tracker.current_board = ["2c", "7d", "Jh", "Qs"]
    tracker.pot_total = 8.0
    glitch_frame = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.7,
        "players": [],
    }
    recovery_frame = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.9,
        "players": [],
    }

    run(tracker.update_from_vision(glitch_frame))
    run(tracker.update_from_vision(recovery_frame))

    assert tracker.state == "TURN"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_board_reset is None
    assert tracker.pending_board_reset_frames == 0


def test_single_frame_pot_drop_candidate_is_cleared_when_next_frame_recovers():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.pot_total = 8.0
    glitch_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.7,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    recovery_frame = {
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 8.0,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(glitch_frame))
    run(tracker.update_from_vision(recovery_frame))

    assert tracker.state == "FLOP"
    assert tracker.current_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pot_total == 8.0
    assert tracker.pending_new_hand_pot is None
    assert tracker.pending_new_hand_frames == 0
    assert tracker.pending_street_promotion == "TURN"
    assert tracker.pending_street_promotion_board == ["2c", "7d", "Jh", "Qs"]
    assert tracker.pending_street_promotion_frames == 1
    assert db.hand_history_calls == []


def test_empty_legal_actions_frame_reuses_previous_actions_for_same_context():
    db = StubDB()
    tracker = TableTracker(db)

    stable_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "legal_actions": ["FOLD", "CALL", "RAISE"],
        "action_buttons": ["fold_button", "call_button", "raise_button"],
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }
    glitch_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.85,
        "legal_actions": [],
        "action_buttons": [],
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(stable_frame))
    run(tracker.update_from_vision(glitch_frame))

    assert tracker.legal_actions == ["FOLD", "CALL", "RAISE"]
    assert tracker.action_buttons == ["fold_button", "call_button", "raise_button"]


def test_state_confidence_one_frame_drop_is_damped_in_same_context():
    db = StubDB()
    tracker = TableTracker(db)

    stable_frame = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 5.5,
        "state_confidence": 0.9,
        "players": [],
    }
    low_confidence_glitch = {
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 5.5,
        "state_confidence": 0.2,
        "players": [],
    }

    run(tracker.update_from_vision(stable_frame))
    run(tracker.update_from_vision(low_confidence_glitch))

    assert tracker.state_confidence == 0.765


def test_hero_flag_glitch_keeps_previous_hero_seat_for_same_players():
    db = StubDB()
    tracker = TableTracker(db)

    stable_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "is_hero": False},
        ],
    }
    glitch_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.85,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": False},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "is_hero": True},
        ],
    }

    run(tracker.update_from_vision(stable_frame))
    run(tracker.update_from_vision(glitch_frame))

    assert tracker.players["hero"].is_hero is True
    assert tracker.players["villain"].is_hero is False
