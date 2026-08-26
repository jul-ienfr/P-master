"""Tests complémentaires du sanity checker : pot reconciliation, stacks, board."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.sanity_checker import SanityChecker


@pytest.fixture()
def checker():
    return SanityChecker()


def test_pot_ignores_unbacked_spike_without_context(checker):
    checker.reset_pot_reconciliation()
    assert checker.validate_pot_evolution(0.0, 80.0, 0.0) == 0.0


def test_pot_accepts_unbacked_spike_when_allowed(checker):
    checker.reset_pot_reconciliation()
    value = checker.validate_pot_evolution(0.0, 80.0, 0.0, allow_unbacked_observed_pot=True)
    assert value == 80.0


def test_pot_accepts_reading_within_margin(checker):
    checker.reset_pot_reconciliation()
    value = checker.validate_pot_evolution(100.0, 103.0, 5.0)
    assert value == 103.0


def test_pot_buffers_spikes_above_expected(checker):
    checker.reset_pot_reconciliation()
    # 100 + 10 mises -> attendu 110 ; OCR lit 200 (pic)
    assert checker.validate_pot_evolution(100.0, 200.0, 10.0) == 110.0
    # l'OCR insiste 3 fois de suite -> réconciliation sur la valeur OCR
    checker.validate_pot_evolution(100.0, 200.0, 10.0)
    reconciled = checker.validate_pot_evolution(100.0, 200.0, 10.0)
    assert reconciled == 200.0


def test_pot_blocks_deflation_beyond_half(checker):
    checker.reset_pot_reconciliation()
    checker.validate_pot_evolution(100.0, 105.0, 10.0)  # établit un pot stable ~115
    expected_before = checker._last_ocr_pot
    blocked = checker.validate_pot_evolution(expected_before + 10.0, 20.0, 10.0)
    # lecture trop basse (<50%) -> on garde le pot mathématique (>0)
    assert blocked >= 20.0


def test_validate_stack_read_bootstrap_accepts_first_positive_read(checker):
    checker.starting_stacks = {}
    assert checker.validate_stack_read(0.0, 1500.0, 0.0, 0.0, seat_id="s1") == 1500.0


def test_validate_stack_read_blocks_impossible_gain(checker):
    result = checker.validate_stack_read(1500.0, 9000.0, 5000.0, 0.0, seat_id="s1")
    assert result == 1500.0


def test_validate_stack_read_blocks_suspicious_crash(checker):
    # chute brutale > 85% avec très peu restant
    result = checker.validate_stack_read(2000.0, 40.0, 5000.0, 0.0, seat_id="s1")
    assert result == 2000.0


def test_validate_stack_read_blocks_micro_fluctuation_on_big_stack(checker):
    result = checker.validate_stack_read(5000.0, 4996.0, 6000.0, 0.0, seat_id="s1")
    assert result == 5000.0


def test_validate_stack_read_zero_read_keeps_current(checker):
    # une lecture à zéro n'est jamais interprétée comme un all-in
    assert checker.validate_stack_read(1200.0, 0.0, 3000.0, 0.0, seat_id="s1") == 1200.0
    assert checker.validate_stack_read(800.0, 0.0, 3000.0, 0.0, seat_id="s2") == 800.0


def test_is_suspect_stack_drop_rules(checker):
    assert checker.is_suspect_stack_drop(0.0, 100.0, 50.0) is False
    assert checker.is_suspect_stack_drop(100.0, 120.0, 50.0) is False
    assert checker.is_suspect_stack_drop(100.0, 30.0, 5.0) is True  # chute > 50%
    assert checker.is_suspect_stack_drop(100.0, 90.0, 1.0) is True  # drop > 3x pot
    assert checker.is_suspect_stack_drop(100.0, 95.0, 50.0) is False


def test_validate_board_cards_coerces_counts(checker):
    cards = ["Ah", "Kd", "Qh", "Js"]
    assert checker.validate_board_cards("PREFLOP", cards) == []
    assert checker.validate_board_cards("IDLE", []) == []
    flop_ok = ["Ah", "Kd", "Qh"]
    assert checker.validate_board_cards("FLOP", flop_ok) == flop_ok
    # turn avec seulement le flop -> inchangé (trop peu)
    assert checker.validate_board_cards("TURN", flop_ok) == flop_ok
    # turn avec 5 cartes -> tronqué à 4
    five = ["Ah", "Kd", "Qh", "Js", "2c"]
    assert len(checker.validate_board_cards("TURN", five)) == 4
    # river complète acceptée
    assert checker.validate_board_cards("RIVER", five) == five
