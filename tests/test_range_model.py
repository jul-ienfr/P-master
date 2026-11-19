import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.range_model import range_class_count, range_classes, range_combo_count
from src.solver.spot_key import spot_cache_key


def test_pair_and_plus_tokens_expand_to_classes():
    assert range_classes("AA") == ("AA",)
    assert range_classes("22+")[0] == "22"
    assert range_classes("22+")[-1] == "AA"
    assert range_class_count("22+") == 13


def test_suited_and_offsuit_combos_are_counted():
    assert range_combo_count("AA") == 6
    assert range_combo_count("AKs") == 4
    assert range_combo_count("AKo") == 12
    assert range_combo_count("AA, AKs, AKo") == 22


def test_plus_suited_token_counts_each_class():
    # A2s+ = A2s .. AKs = 12 classes × 4 combos
    assert range_class_count("A2s+") == 12
    assert range_combo_count("A2s+") == 48


def test_empty_or_invalid_notation_has_zero_combos():
    assert range_combo_count("") == 0
    assert range_combo_count("  ,  ") == 0
    assert range_combo_count("ZZ") == 0


def test_spot_cache_key_separates_hero_ranges_but_stays_stable_when_absent():
    base = {
        "hero_hand": "AhKd",
        "villain_range": "QQ+,AK",
        "board": ["2c", "7d", "Jh"],
        "pot": 10.0,
        "effective_stack": 80.0,
        "legal_actions": ["CHECK", "BET"],
        "spot_id": "s1",
        "hero_position": "BTN",
        "action_history": [],
    }
    legacy = spot_cache_key(**base)
    same = spot_cache_key(**base)
    multi = spot_cache_key(**base, hero_range="22+, A2s+, AKo")
    other = spot_cache_key(**base, hero_range="22+, A2s+, KQo")

    assert legacy == same
    assert multi != legacy
    assert multi != other
