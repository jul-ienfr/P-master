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


from src.bot import sanity_checker as sanity_module
from src.bot.table_tracker import PlayerState, TableTracker


class StubDB:
    def __init__(self):
        self.observed_calls = []
        self.action_updates = []
        self.hand_history_calls = []
        self.merge_calls = []

    async def record_observed_hand(self, player_name: str, street: str = "UNKNOWN"):
        self.observed_calls.append((player_name, street))

    async def update_player_action(self, player_name: str, action_data: dict):
        self.action_updates.append((player_name, action_data))

    async def insert_hand_history(self, table_name: str, board: list, actions: list):
        self.hand_history_calls.append((table_name, list(board), list(actions)))

    async def merge_player_profiles(self, source_name: str, target_name: str):
        self.merge_calls.append((source_name, target_name))


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


def test_placeholder_observation_profile_is_merged_when_real_name_appears():
    db = StubDB()
    tracker = TableTracker(db)

    nameless_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "seat_1", "seat_index": 1, "name": "", "stack": 100.0},
        ],
    }
    named_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "players": [
            {"seat_id": "seat_1", "seat_index": 1, "name": "Brucy20", "stack": 100.0},
        ],
    }

    run(tracker.update_from_vision(nameless_frame))
    run(tracker.update_from_vision(named_frame))

    assert db.observed_calls == [("seat_1", "PREFLOP")]
    assert db.merge_calls == [("seat_1", "Brucy20")]
    assert tracker.players["seat_1"].name == "Brucy20"


def test_preflop_vpip_and_pfr_flags_are_counted_once_per_hand():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "PREFLOP"

    run(tracker._record_action("Villain", "RAISE/BET", 2.0))
    run(tracker._record_action("Villain", "RAISE/BET", 4.0))

    assert len(db.action_updates) == 2
    first_action = db.action_updates[0][1]
    second_action = db.action_updates[1][1]
    assert first_action["counts_towards_vpip"] == 1
    assert first_action["counts_towards_pfr"] == 1
    assert second_action["counts_towards_vpip"] == 0
    assert second_action["counts_towards_pfr"] == 0


def test_saved_hand_history_sanitizes_names_and_removes_duplicate_or_post_fold_actions():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.current_board = ["Ah", "Kd", "2c", "7d", "Jh"]
    tracker.current_hand_actions = [
        {"player": ".<br>NTFmango", "action": "CALL", "amount": 8.0, "pot_size": 900.0, "street": "RIVER"},
        {"player": ".<br>NTFmango", "action": "CALL", "amount": 8.0, "pot_size": 900.0, "street": "RIVER"},
        {"player": "Villain", "action": "FOLD", "amount": 0.0, "pot_size": 900.0, "street": "RIVER"},
        {"player": "Villain", "action": "RAISE/BET", "amount": 25.0, "pot_size": 900.0, "street": "RIVER"},
    ]

    run(tracker._save_hand_history())

    assert len(db.hand_history_calls) == 1
    _, _, actions = db.hand_history_calls[0]
    assert actions == [
        {"player": "NTFmango", "action": "CALL", "amount": 8.0, "pot_size": 900.0, "street": "RIVER"},
        {"player": "Villain", "action": "FOLD", "amount": 0.0, "pot_size": 900.0, "street": "RIVER"},
    ]


def test_multiple_hands_can_be_saved_across_consecutive_resets():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.current_board = ["Ah", "Kd", "2c"]
    tracker.current_hand_actions = [
        {"player": "VillainA", "action": "CALL", "amount": 2.0, "pot_size": 3.0, "street": "PREFLOP"},
    ]
    run(tracker._save_hand_history())
    tracker.reset_for_new_hand()

    tracker.current_board = ["7h", "8h", "9c", "Td"]
    tracker.current_hand_actions = [
        {"player": "VillainB", "action": "RAISE/BET", "amount": 12.0, "pot_size": 18.0, "street": "TURN"},
    ]
    run(tracker._save_hand_history())

    assert len(db.hand_history_calls) == 2
    assert db.hand_history_calls[0][1] == ["Ah", "Kd", "2c"]
    assert db.hand_history_calls[1][1] == ["7h", "8h", "9c", "Td"]


def test_observed_hand_without_detected_actions_is_still_saved_when_hand_ends():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.hero_cards = ["Ah", "Kd"]
    tracker.observed_players_this_hand = {"seat_1", "seat_2"}

    run(tracker._save_hand_history())

    assert len(db.hand_history_calls) == 1
    table_name, board, actions = db.hand_history_calls[0]
    assert table_name == "Table_1"
    assert board == ["2c", "7d", "Jh"]
    assert actions == []


def test_distinct_flop_board_rollover_saves_previous_hand_and_tracks_new_one():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.hero_cards = ["Ah", "Kd"]
    tracker.observed_players_this_hand = {"seat_1"}

    new_flop_frame = {
        "street": "FLOP",
        "board": ["5s", "4h", "7h"],
        "hero_cards": ["Qs", "Qc"],
        "pot": 3.0,
        "players": [],
    }

    run(tracker.update_from_vision(new_flop_frame))

    assert len(db.hand_history_calls) == 1
    assert db.hand_history_calls[0][1] == ["2c", "7d", "Jh"]
    assert tracker.state == "FLOP"
    assert tracker.current_board == ["5s", "4h", "7h"]


def test_single_card_board_correction_does_not_trigger_rollover():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "FLOP"
    tracker.current_board = ["Ad", "Th", "4h"]
    tracker.hero_cards = ["Ah", "Kd"]
    tracker.observed_players_this_hand = {"seat_1"}

    corrected_flop_frame = {
        "street": "FLOP",
        "board": ["Ad", "Td", "4h"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 3.0,
        "players": [],
    }

    run(tracker.update_from_vision(corrected_flop_frame))

    assert db.hand_history_calls == []
    assert tracker.state == "FLOP"
    assert tracker.current_board == ["Ad", "Td", "4h"]


def test_board_reset_into_fresh_preflop_snapshot_saves_previous_hand_immediately():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "RIVER"
    tracker.current_board = ["Ad", "Td", "4h", "7d", "2c"]
    tracker.hero_cards = ["Ah", "Kd"]
    tracker.observed_players_this_hand = {"seat_1"}

    next_hand_frame = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Qs", "Qc"],
        "pot": 1.5,
        "players": [],
    }

    run(tracker.update_from_vision(next_hand_frame))

    assert len(db.hand_history_calls) == 1
    assert db.hand_history_calls[0][1] == ["Ad", "Td", "4h", "7d", "2c"]
    assert tracker.state == "PREFLOP"
    assert tracker.current_board == []
    assert tracker.hero_cards == ["Qs", "Qc"]


def test_distinct_hero_rollover_starts_new_preflop_hand_without_waiting_for_reset_frames():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "PREFLOP"
    tracker.hero_cards = ["Ah", "Kd"]
    tracker.observed_players_this_hand = {"seat_1"}

    next_hand_frame = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Qs", "Qc"],
        "pot": 1.5,
        "players": [],
    }

    run(tracker.update_from_vision(next_hand_frame))

    assert len(db.hand_history_calls) == 1
    assert tracker.state == "PREFLOP"
    assert tracker.current_board == []
    assert tracker.hero_cards == ["Qs", "Qc"]


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
    assert tracker.pending_board_reset is None
    assert tracker.pending_board_reset_frames == 0

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
    assert tracker.state == "PREFLOP"
    assert tracker.current_hand_actions == []


def test_folded_player_is_not_reactivated_by_noisy_followup_frame():
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "active": True},
        ],
    }
    fold_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0, "active": False, "folded": True},
        ],
    }
    noisy_reactivation_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.7,
        "players": [
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 0.0, "active": True, "folded": False},
        ],
    }

    run(tracker.update_from_vision(opening_state))
    run(tracker.update_from_vision(fold_state))
    run(tracker.update_from_vision(noisy_reactivation_state))

    assert len(db.action_updates) == 1
    assert db.action_updates[0][1]["action"] == "FOLD"


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


def test_strict_state_violation_freezes_tracker_for_half_second(monkeypatch):
    fake_now = {"value": 10.0}
    monkeypatch.setattr("src.bot.table_tracker.time.monotonic", lambda: fake_now["value"])

    db = StubDB()
    tracker = TableTracker(db)
    tracker.state = "FLOP"
    tracker.current_board = ["2c", "7d", "Jh"]
    tracker.confirmed_board = ["2c", "7d", "Jh"]

    invalid_jump = {
        "street": "RIVER",
        "board": ["As", "Kd", "Qc", "Jh", "Ts"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 18.0,
        "players": [],
    }

    run(tracker.update_from_vision(invalid_jump))

    assert tracker.state == "FLOP"
    assert tracker._is_state_frozen() is True
    assert tracker.state_freeze_reason.startswith("street_jump")

    fake_now["value"] = 10.2
    run(tracker.update_from_vision({
        "street": "TURN",
        "board": ["2c", "7d", "Jh", "Qs"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 18.0,
        "players": [],
    }))

    assert tracker.state == "FLOP"
    assert tracker.current_board == ["2c", "7d", "Jh"]

    fake_now["value"] = 10.6
    run(tracker.update_from_vision({
        "street": "FLOP",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 18.0,
        "players": [],
    }))

    assert tracker._is_state_frozen() is False


def test_save_hand_history_uses_confirmed_board_cache_when_current_board_is_candidate():
    db = StubDB()
    tracker = TableTracker(db)
    tracker.confirmed_board = ["2c", "7d", "Jh"]
    tracker.current_board = ["2c", "7d", "Jh", "Qs"]
    tracker.observed_players_this_hand = {"seat_1"}

    run(tracker._save_hand_history())

    assert db.hand_history_calls[0][1] == ["2c", "7d", "Jh"]


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


def test_first_postflop_ocr_pot_is_kept_without_stack_deltas():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "PREFLOP"
    tracker.hero_cards = ["Ah", "Kd"]

    first_flop_snapshot = {
        "street": "TURN",
        "board": ["3d", "2d", "7d", "Kd"],
        "hero_cards": ["6d", "3h"],
        "pot": 1837.0,
        "state_confidence": 0.96,
        "legal_actions": ["CHECK", "BET"],
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }

    run(tracker.update_from_vision(first_flop_snapshot))

    assert tracker.pot_total == 1837.0
    assert tracker.last_pot == 0.0
    assert tracker.state in {"FLOP", "TURN"}


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


def test_observing_hand_with_board_can_adopt_unbacked_observed_pot_immediately():
    db = StubDB()
    tracker = TableTracker(db)

    tracker.state = "IDLE"
    tracker.current_board = []
    tracker.pot_total = 0.0

    observing_board_frame = {
        "street": "FLOP",
        "board": ["3d", "7h", "8d"],
        "hero_cards": [],
        "pot": 11828.0,
        "state_confidence": 0.7,
        "legal_actions": [],
        "players": [],
        "metadata": {
            "observation_mode": True,
            "hero_participation": "observing_hand",
            "observation_street": "FLOP",
        },
    }

    run(tracker.update_from_vision(observing_board_frame))

    assert tracker.pot_total == 11828.0


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


def test_zero_stack_ocr_does_not_create_phantom_all_in_action():
    db = StubDB()
    tracker = TableTracker(db)

    opening_state = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 3.0,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
        ],
    }
    noisy_followup_state = {
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 3.0,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 0.0},
        ],
    }

    run(tracker.update_from_vision(opening_state))
    run(tracker.update_from_vision(noisy_followup_state))

    assert tracker.players["villain"].current_stack == 100.0
    assert tracker.current_hand_actions == []
    assert tracker.pot_total == 0.0


def test_idle_table_reanchors_large_stack_change_without_warning_flood(caplog):
    db = StubDB()
    tracker = TableTracker(db)

    tracker.players["seat_1"] = PlayerState(
        seat_id="seat_1",
        seat_index=1,
        name="VillainA",
        starting_stack=11873.0,
        current_stack=11873.0,
    )
    tracker.players["seat_2"] = PlayerState(
        seat_id="seat_2",
        seat_index=2,
        name="VillainB",
        starting_stack=5600.0,
        current_stack=5600.0,
    )

    idle_snapshot = {
        "street": "IDLE",
        "board": [],
        "hero_cards": [],
        "pot": 0.0,
        "action_buttons": ["resume_hand"],
        "players": [
            {"seat_id": "seat_1", "seat_index": 1, "name": "VillainA", "stack": 12212.0},
            {"seat_id": "seat_2", "seat_index": 2, "name": "VillainB", "stack": 39902.0},
        ],
    }

    with caplog.at_level(logging.WARNING, logger="SanityChecker"):
        run(tracker.update_from_vision(idle_snapshot))
        run(tracker.update_from_vision(idle_snapshot))

    assert tracker.players["seat_1"].current_stack == 12212.0
    assert tracker.players["seat_1"].starting_stack == 12212.0
    assert tracker.players["seat_2"].current_stack == 39902.0
    assert tracker.players["seat_2"].starting_stack == 39902.0
    assert "Anomalie Stack bloquée" not in caplog.text


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

    assert tracker.state_confidence == 0.675


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


def test_stack_bootstrap_recovers_after_initial_zero_reads():
    db = StubDB()
    tracker = TableTracker(db)

    zero_stack_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 0.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 0.0},
        ],
    }
    recovered_stack_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.92,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 80.0},
        ],
    }

    run(tracker.update_from_vision(zero_stack_frame))
    run(tracker.update_from_vision(recovered_stack_frame))

    assert tracker.players["hero"].starting_stack == 100.0
    assert tracker.players["hero"].current_stack == 100.0
    assert tracker.players["villain"].starting_stack == 80.0
    assert tracker.players["villain"].current_stack == 80.0
    assert tracker.get_primary_villain().name == "Villain"
    assert tracker.get_effective_stack() == 80.0


def test_inactive_glitch_without_explicit_fold_does_not_remove_villain():
    db = StubDB()
    tracker = TableTracker(db)

    stable_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 80.0},
        ],
    }
    glitch_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.84,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 0.0, "active": False, "folded": False},
        ],
    }
    recovery_frame = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
            {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 80.0},
        ],
    }

    run(tracker.update_from_vision(stable_frame))
    run(tracker.update_from_vision(glitch_frame))
    run(tracker.update_from_vision(recovery_frame))

    assert tracker.players["villain"].has_folded is False
    assert tracker.players["villain"].is_active is True
    assert tracker.get_primary_villain().name == "Villain"
    assert tracker.get_effective_stack() == 80.0


def test_resolve_clean_stack_keeps_existing_seat_quarantine(monkeypatch):
    fake_now = {"value": 50.0}
    monkeypatch.setattr(sanity_module.time, "monotonic", lambda: fake_now["value"])

    db = StubDB()
    tracker = TableTracker(db)
    tracker.players["villain"] = PlayerState(
        seat_id="villain",
        seat_index=1,
        name="Villain",
        starting_stack=80.0,
        current_stack=80.0,
    )
    tracker.sanity.validate_stack_read(80.0, 570.0, 80.0, 0.0, seat_id="villain")
    assert tracker.sanity.is_stack_read_quarantined("villain") is True

    fake_now["value"] = 50.2
    clean_stack = tracker._resolve_clean_stack(
        player=tracker.players["villain"],
        ocr_stack=80.0,
        seat_id="villain",
        stack_ocr_metadata={"skipped_due_to_quarantine": True},
    )

    assert clean_stack == 80.0
    assert tracker.sanity.is_stack_read_quarantined("villain") is True


def test_update_lock_serializes_concurrent_updates():
    db = StubDB()
    tracker = TableTracker(db)

    call_order = []

    original_unlocked = tracker._update_from_vision_unlocked

    async def slow_update(vision_state):
        call_order.append("enter")
        await original_unlocked(vision_state)
        call_order.append("exit")

    tracker._update_from_vision_unlocked = slow_update

    vision_state = {
        "street": "PREFLOP",
        "hero_cards": ["Ah", "Kd"],
        "pot": 1.5,
        "state_confidence": 0.9,
        "players": [
            {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
        ],
    }

    async def run_concurrent():
        await asyncio.gather(
            tracker.update_from_vision(dict(vision_state)),
            tracker.update_from_vision(dict(vision_state)),
        )

    asyncio.run(run_concurrent())

    assert call_order == ["enter", "exit", "enter", "exit"]


def test_safe_fire_and_forget_logs_exception_without_crash(caplog):
    db = StubDB()
    tracker = TableTracker(db)

    async def failing_coro():
        raise RuntimeError("simulated db failure")

    async def run_test():
        tracker._safe_fire_and_forget(failing_coro(), task_name="test_task")
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.ERROR, logger="TableTracker"):
        asyncio.run(run_test())

    assert "test_task" in caplog.text
    assert "simulated db failure" in caplog.text


def test_safe_fire_and_forget_completes_successfully():
    db = StubDB()
    tracker = TableTracker(db)
    results = []

    async def good_coro():
        results.append("done")

    async def run_test():
        tracker._safe_fire_and_forget(good_coro(), task_name="good_task")
        await asyncio.sleep(0.05)

    asyncio.run(run_test())

    assert results == ["done"]
