import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.live_reconstruction import (
    derive_legal_actions,
    derive_street,
    infer_hero_seat_id,
    normalize_board_for_street,
    ordered_stacks_by_table_geometry,
    smooth_state_confidence_window,
    stable_window_value,
)


def test_derive_street_prefers_board_card_count():
    assert derive_street(["2c", "7d", "Jh"], ["Ah", "Kd"]) == "FLOP"
    assert derive_street(["2c", "7d", "Jh", "Qs"], ["Ah", "Kd"]) == "TURN"
    assert derive_street(["2c", "7d", "Jh", "Qs", "Ac"], ["Ah", "Kd"]) == "RIVER"


def test_derive_street_falls_back_to_preflop_or_idle():
    assert derive_street([], ["Ah", "Kd"]) == "PREFLOP"
    assert derive_street([], ["Ah"]) == "IDLE"


def test_normalize_board_for_street_trims_to_expected_count():
    board = ("2c", "7d", "Jh", "Qs", "Ac")

    assert normalize_board_for_street(board, "FLOP") == ("2c", "7d", "Jh")
    assert normalize_board_for_street(board, "TURN") == ("2c", "7d", "Jh", "Qs")
    assert normalize_board_for_street(board, "PREFLOP") == ()


def test_derive_legal_actions_normalizes_buttons_and_prefers_raise_over_bet():
    legal_actions, action_buttons = derive_legal_actions(
        ["fold_button", "call_button", "bet_button", "raise_button", "fold_button"]
    )

    assert legal_actions == ("FOLD", "CALL", "RAISE")
    assert action_buttons == ("fold_button", "call_button", "bet_button", "raise_button")


def test_derive_legal_actions_maps_check_and_all_in_call():
    legal_actions, action_buttons = derive_legal_actions(["check_button", "all_in_call_button"])

    assert legal_actions == ("CHECK", "CALL")
    assert action_buttons == ("check_button", "all_in_call_button")


def test_stable_window_value_prefers_recent_majority_over_empty_glitch():
    assert stable_window_value(
        [("FOLD", "CALL"), ("FOLD", "CALL")],
        (),
        ignore_values=((),),
    ) == ("FOLD", "CALL")


def test_stable_window_value_keeps_incoming_when_it_ties_for_majority():
    assert stable_window_value(["PREFLOP", "FLOP"], "TURN") == "TURN"


def test_smooth_state_confidence_window_damps_single_frame_drop():
    assert smooth_state_confidence_window([0.9], 0.2) == 0.765


def test_smooth_state_confidence_window_allows_recovery_to_higher_confidence():
    assert smooth_state_confidence_window([0.765], 0.92) == 0.92


def test_ordered_stacks_by_table_geometry_assigns_stable_clockwise_seats():
    stacks = [
        (470, 500, 530, 540),
        (120, 300, 180, 340),
        (470, 80, 530, 120),
        (820, 300, 880, 340),
    ]

    ordered = ordered_stacks_by_table_geometry(stacks, frame_shape=(600, 1000), pot_bbox=(470, 280, 530, 320))

    assert ordered == [
        ("seat_0", (470, 80, 530, 120)),
        ("seat_1", (820, 300, 880, 340)),
        ("seat_2", (470, 500, 530, 540)),
        ("seat_3", (120, 300, 180, 340)),
    ]


def test_infer_hero_seat_id_picks_bottom_center_stack_from_hero_cards():
    ordered_stacks = [
        ("seat_0", (470, 500, 530, 540)),
        ("seat_1", (120, 300, 180, 340)),
        ("seat_2", (470, 80, 530, 120)),
        ("seat_3", (820, 300, 880, 340)),
    ]
    hero_cards = [(430, 520, 460, 570), (540, 520, 570, 570)]

    assert infer_hero_seat_id(ordered_stacks, hero_cards, frame_shape=(600, 1000)) == "seat_0"


def test_infer_hero_seat_id_reuses_last_seen_seat_when_cards_missing():
    ordered_stacks = [
        ("seat_0", (470, 500, 530, 540)),
        ("seat_1", (120, 300, 180, 340)),
    ]

    assert infer_hero_seat_id(
        ordered_stacks,
        hero_card_bboxes=[],
        frame_shape=(600, 1000),
        last_hero_seat_id="seat_1",
    ) == "seat_1"


def test_infer_hero_seat_id_keeps_prior_seat_when_it_remains_top_two_candidate():
    ordered_stacks = [
        ("seat_0", (470, 500, 530, 540)),
        ("seat_1", (550, 490, 610, 530)),
        ("seat_2", (120, 300, 180, 340)),
    ]
    hero_cards = [(520, 500, 550, 560), (560, 500, 590, 560)]

    assert infer_hero_seat_id(
        ordered_stacks,
        hero_cards,
        frame_shape=(600, 1000),
        last_hero_seat_id="seat_0",
    ) == "seat_0"


def test_infer_hero_seat_id_keeps_prior_seat_when_scores_are_still_close():
    ordered_stacks = [
        ("seat_0", (470, 500, 530, 540)),
        ("seat_1", (610, 470, 670, 510)),
        ("seat_2", (120, 300, 180, 340)),
    ]
    hero_cards = [(590, 490, 620, 560), (625, 490, 655, 560)]

    assert infer_hero_seat_id(
        ordered_stacks,
        hero_cards,
        frame_shape=(600, 1000),
        last_hero_seat_id="seat_0",
    ) == "seat_0"
