import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot import sanity_checker as sanity_module
from src.bot.sanity_checker import ActionIntent, SanityChecker


def test_action_intent_normalizes_payload():
    intent = ActionIntent.from_payload({"action": "raise", "bet_size": "12.5", "source": "solver"})

    assert intent.action == "RAISE"
    assert intent.bet_size == 12.5
    assert intent.source == "solver"


def test_action_intent_ignores_invalid_bet_size():
    intent = ActionIntent.from_payload({"action": "bet", "bet_size": "oops"})

    assert intent.action == "BET"
    assert intent.bet_size is None


def test_evaluate_action_gate_allows_consistent_runtime_action():
    checker = SanityChecker()
    result = checker.evaluate_action_gate(
        action_intent=ActionIntent(action="CALL", source="unit-test"),
        tracker_state={
            "hero_cards": ["Ah", "Kd"],
            "board": ["2c", "7d", "Jh"],
            "pot": 42.0,
            "street": "FLOP",
            "legal_actions": ["fold", "call"],
            "in_hand": True,
            "state_confidence": 0.91,
        },
        coords_mapping={"CALL": (100, 200)},
    )

    assert result.allowed is True
    assert result.status == "allowed"
    assert result.reasons == []
    assert result.confidence == 0.91


def test_evaluate_action_gate_blocks_incoherent_or_illegal_action():
    checker = SanityChecker()
    result = checker.evaluate_action_gate(
        action_intent=ActionIntent(action="RAISE", bet_size=18.0, source="unit-test"),
        tracker_state={
            "hero_cards": ["Ah", "Kd"],
            "board": ["2c", "7d", "Jh"],
            "pot": 42.0,
            "street": "TURN",
            "legal_actions": ["FOLD", "CALL"],
            "in_hand": True,
            "state_confidence": 0.8,
        },
        coords_mapping={"BET_BOX": (10, 10), "BET_BTN": (20, 20)},
    )

    reason_codes = {reason.code for reason in result.reasons}
    assert result.allowed is False
    assert result.status == "blocked"
    assert "STATE_INCOHERENT" in reason_codes
    assert "ILLEGAL_ACTION" in reason_codes


def test_evaluate_action_gate_marks_soft_runtime_uncertainty():
    checker = SanityChecker()
    result = checker.evaluate_action_gate(
        action_intent=ActionIntent(action="BET", source="unit-test"),
        tracker_state={
            "hero_cards": ["Ah", "Kd"],
            "board": [],
            "pot": 3.0,
            "street": "PREFLOP",
            "legal_actions": ["BET", "FOLD"],
            "in_hand": True,
            "state_confidence": 0.2,
        },
        coords_mapping={"BET_BOX": (10, 10), "BET_BTN": (20, 20)},
    )

    reason_codes = {reason.code for reason in result.reasons}
    assert result.allowed is False
    assert result.status == "uncertain"
    assert reason_codes == {"LOW_STATE_CONFIDENCE", "BET_SIZE_MISSING"}


def test_evaluate_action_gate_calls_failure_callback_when_blocked():
    checker = SanityChecker()
    recorded = []

    result = checker.evaluate_action_gate(
        action_intent=ActionIntent(action="CALL", source="unit-test"),
        tracker_state={
            "hero_cards": [],
            "board": ["2c", "7d", "Jh"],
            "pot": 42.0,
            "street": "TURN",
            "legal_actions": ["FOLD"],
            "in_hand": False,
            "state_confidence": 0.8,
        },
        coords_mapping={"CALL": (10, 10)},
        on_failure=lambda gate_result: recorded.append(gate_result.reason),
    )

    assert result.allowed is False
    assert recorded == [result.reason]


def test_validate_board_cards_trims_unstable_turn_frame():
    checker = SanityChecker()

    assert checker.validate_board_cards("TURN", ["2c", "7d", "Jh", "Qs", "Ac"]) == ["2c", "7d", "Jh", "Qs"]


def test_validate_board_cards_drops_invalid_preflop_ghost_cards():
    checker = SanityChecker()

    assert checker.validate_board_cards("PREFLOP", ["2c", "7d"]) == []


def test_validate_pot_evolution_normalizes_invalid_numeric_inputs():
    checker = SanityChecker()

    assert checker.validate_pot_evolution("5.5", "7.0", "1.5") == 7.0
    assert checker.validate_pot_evolution(None, "oops", object()) == 0.0


def test_validate_pot_evolution_blocks_only_upward_ocr_hallucinations():
    checker = SanityChecker()

    assert checker.validate_pot_evolution(5.5, 12.0, 1.0) == 6.5
    assert checker.validate_pot_evolution(5.5, 6.0, 3.0) == 6.0


def test_validate_pot_evolution_accepts_zero_reset_for_plausible_new_hand():
    checker = SanityChecker()

    assert checker.validate_pot_evolution(8.0, 0.0, 0.0) == 0.0


def test_reset_pot_reconciliation_clears_buffered_state():
    checker = SanityChecker()
    checker._pot_discrepancy_count = 2
    checker._last_ocr_pot = 8.0

    checker.reset_pot_reconciliation()

    assert checker._pot_discrepancy_count == 0
    assert checker._last_ocr_pot == -1.0


def test_is_possible_new_hand_pot_only_flags_small_downward_reset_like_pots():
    checker = SanityChecker()

    assert checker.is_possible_new_hand_pot(12.0, 1.5) is True
    assert checker.is_possible_new_hand_pot(12.0, 0.0) is True
    assert checker.is_possible_new_hand_pot(12.0, 6.0) is False
    assert checker.is_possible_new_hand_pot(0.0, 1.5) is False


def test_is_possible_board_reset_only_flags_downward_board_transitions():
    checker = SanityChecker()

    assert checker.is_possible_board_reset(["2c", "7d", "Jh"], []) is True
    assert checker.is_possible_board_reset(["2c", "7d", "Jh"], ["2c", "7d", "Jh", "Qs"]) is False
    assert checker.is_possible_board_reset([], []) is False


def test_is_same_hand_board_transition_only_flags_single_card_prefix_changes():
    checker = SanityChecker()

    assert checker.is_same_hand_board_transition(["2c", "7d", "Jh"], ["2c", "7d", "Jh", "Qs"]) is True
    assert checker.is_same_hand_board_transition(["2c", "7d", "Jh", "Qs"], ["2c", "7d", "Jh"]) is True
    assert checker.is_same_hand_board_transition(["2c", "7d", "Jh"], []) is False
    assert checker.is_same_hand_board_transition(["2c", "7d", "Jh"], ["2c", "7d", "Td"]) is False


def test_requires_multiframe_street_confirmation_only_for_ambiguous_turn_and_river_promotions():
    checker = SanityChecker()

    assert checker.requires_multiframe_street_confirmation(
        current_street="FLOP",
        candidate_street="TURN",
        current_board=["2c", "7d", "Jh"],
        new_board=["2c", "7d", "Jh", "Qs"],
    ) is True
    assert checker.requires_multiframe_street_confirmation(
        current_street="TURN",
        candidate_street="RIVER",
        current_board=["2c", "7d", "Jh", "Qs"],
        new_board=["2c", "7d", "Jh", "Qs", "Ac"],
    ) is True
    assert checker.requires_multiframe_street_confirmation(
        current_street="PREFLOP",
        candidate_street="FLOP",
        current_board=[],
        new_board=["2c", "7d", "Jh"],
    ) is False
    assert checker.requires_multiframe_street_confirmation(
        current_street="FLOP",
        candidate_street="TURN",
        current_board=["2c", "7d", "Jh"],
        new_board=["2c", "7d", "Jh"],
    ) is False


def test_validate_stack_read_rate_limits_duplicate_warnings_per_seat(monkeypatch, caplog):
    checker = SanityChecker()
    fake_now = {"value": 100.0}
    monkeypatch.setattr(sanity_module.time, "monotonic", lambda: fake_now["value"])

    with caplog.at_level(logging.WARNING, logger="SanityChecker"):
        assert checker.validate_stack_read(100.0, 570.0, 100.0, 0.0, seat_id="seat_1") == 100.0
        assert checker.is_stack_read_quarantined("seat_1") is True

        fake_now["value"] = 100.2
        assert checker.validate_stack_read(100.0, 45507.0, 100.0, 0.0, seat_id="seat_1") == 100.0

    warning_messages = [record.getMessage() for record in caplog.records if "Anomalie Stack bloquée" in record.getMessage()]
    assert len(warning_messages) == 1

    fake_now["value"] = 101.3
    assert checker.is_stack_read_quarantined("seat_1") is False


def test_validate_stack_read_keeps_previous_stack_when_ocr_temporarily_reads_zero():
    checker = SanityChecker()

    assert checker.validate_stack_read(100.0, 0.0, 87.5, 0.0, seat_id="seat_1") == 87.5
