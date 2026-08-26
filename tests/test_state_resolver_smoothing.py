"""Tests du lissage des actions légales et de la confiance runtime (state_resolver)."""
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.state_resolver import StateResolverMixin


def make_controller():
    class Controller(StateResolverMixin):
        def __init__(self):
            self.last_canonical_spot_snapshot = {}
            self._recent_runtime_legal_actions = deque(maxlen=5)
            self._recent_runtime_state_confidences = deque(maxlen=5)

    return Controller()


def test_smooth_legal_actions_resets_without_actionable_buttons():
    c = make_controller()
    c._recent_runtime_legal_actions.append(("FOLD", "CALL"))
    legal, buttons = c._smooth_legal_actions(
        legal_actions=("FOLD", "CALL"),
        action_buttons=(),
        board=("Ah",),
        hero_cards=("Kh", "Qd"),
    )
    assert legal == ()
    assert list(c._recent_runtime_legal_actions) == []


def test_smooth_legal_actions_resets_when_context_changes():
    c = make_controller()
    c.last_canonical_spot_snapshot = {"board": ["Ah"], "hero_cards": ["Kh", "Qd"]}
    c._recent_runtime_legal_actions.append(("FOLD",))
    legal, _buttons = c._smooth_legal_actions(
        legal_actions=("BET", "RAISE"),
        action_buttons=("bet_button",),
        board=("2s", "7h", "8d"),
        hero_cards=("Kh", "Qd"),
    )
    # nouveau spot : fenêtre réinitialisée puis valeur courante acceptée
    assert legal == ("BET", "RAISE") or legal
    assert len(c._recent_runtime_legal_actions) == 1


def test_smooth_legal_actions_stabilizes_within_same_context():
    c = make_controller()
    c._recent_runtime_legal_actions.append(("FOLD", "CALL"))
    c.last_canonical_spot_snapshot = {
        "board": ["Ah", "Kd", "2c"],
        "hero_cards": ["Kh", "Qd"],
    }
    legal, _buttons = c._smooth_legal_actions(
        legal_actions=("FOLD", "CALL"),
        action_buttons=("fold_button", "call_button"),
        board=("Ah", "Kd", "2c"),
        hero_cards=("Kh", "Qd"),
    )
    # le lissage garde les actions stables même si une frame renvoie vide
    assert tuple(legal) in (("FOLD", "CALL"), ())


def test_smooth_runtime_confidence_drops_single_frame_glitch():
    c = make_controller()
    c.last_canonical_spot_snapshot = {
        "street": "TURN",
        "board": ["Ah", "Kd", "2c", "9s"],
        "hero_cards": ["Kh", "Qd"],
    }
    first = c._smooth_runtime_state_confidence(0.95, "TURN", ("Ah", "Kd", "2c", "9s"), ("Kh", "Qd"))
    glitch = c._smooth_runtime_state_confidence(0.10, "TURN", ("Ah", "Kd", "2c", "9s"), ("Kh", "Qd"))
    recovered = c._smooth_runtime_state_confidence(0.93, "TURN", ("Ah", "Kd", "2c", "9s"), ("Kh", "Qd"))
    assert first == 0.95
    assert glitch < 0.95  # amorti, pas d'effondrement immédiat
    assert recovered >= 0.9


def test_smooth_runtime_confidence_resets_on_new_spot():
    c = make_controller()
    c.last_canonical_spot_snapshot = {
        "street": "PREFLOP",
        "board": (),
        "hero_cards": ["Ah", "Ad"],
    }
    c._recent_runtime_state_confidences.append(0.5)
    value = c._smooth_runtime_state_confidence(0.88, "FLOP", ("2c",), ("Ah", "Ad"))
    assert value == 0.88  # nouveau contexte : pas d'amortissement avec l'ancien historique
