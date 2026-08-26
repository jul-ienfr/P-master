"""Tests complémentaires gate_flow : compact payload branches, transition, readiness failure."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.gate_flow import GateFlowMixin, compact_solver_payload
from src.bot.runtime_types import CanonicalTableState
from src.runtime.session import RuntimeSessionMixin
from src.vision.table_geometry import safe_crop


class Controller(GateFlowMixin, RuntimeSessionMixin):
    _safe_crop = staticmethod(safe_crop)
    def __init__(self):
        self.events = []
        self._last_runtime_street = "IDLE"
        self.last_decision_summary = {}
        self._last_runtime_readiness_failure_signature = ()
        self._last_runtime_readiness_failure_at = 0.0
        self.last_valid_frame = np.zeros((8, 8, 3), dtype=np.uint8)
        self.last_resolved_runtime_state = None

    def _push_runtime_event(self, kind, message, **context):
        self.events.append((kind, message, context))


def test_compact_solver_payload_drops_non_list_warning_fields():
    payload = {
        "warnings": None,
        "warning_details": "not-a-list",
        "action_buckets": 12,
        "alternatives": [],
        "backend": "x",
    }
    compact = compact_solver_payload(payload)
    assert compact["warnings"] is None  # None conservé tel quel
    assert "warning_details" not in compact
    assert "action_buckets" not in compact

    # listes valides : dicts conservés, autres valeurs stringifiées, vides filtrées
    filled = compact_solver_payload(
        {
            "warning_details": [{"k": 1}, "raw", "   "],
            "action_buckets": [{"b": 2}],
            "warnings": ["w1"],
        }
    )
    assert filled["warning_details"] == [{"k": 1}, "raw"]
    assert filled["action_buckets"] == [{"b": 2}]


def test_record_runtime_failure_swallows_shadow_capture_errors():
    c = Controller()
    c.operator_controls = {"shadow_mode_enabled": True}

    class ExplodingHitl:
        def record_shadow_failure(self, *args, **kwargs):
            raise RuntimeError("hitl down")

    c.hitl = ExplodingHitl()
    c.last_tracker_snapshot = {}
    c.last_decision_summary = {}
    c.runtime_failure_dataset = None  # dataset absent : retour immédiat avant hitl

    c._record_runtime_failure(category="vision", incident_id="i1")
    # maintenant avec un dataset factice pour atteindre le bloc hitl protégé
    recorded = []
    c.runtime_failure_dataset = SimpleNamespace(record_incident=lambda p: recorded.append(p))
    c._record_runtime_failure(category="vision", incident_id="i2")
    assert recorded and recorded[0]["incident_id"] == "i2"


def test_record_runtime_transition_pushes_event_on_street_change():
    c = Controller()
    c._record_runtime_transition({"street": "FLOP", "board": [], "pot": 0.0})
    assert c._last_runtime_street == "FLOP"
    assert c.events and c.events[0][0] == "tracker"

    # même rue -> pas de nouvel événement
    before = len(c.events)
    c._record_runtime_transition({"street": "FLOP"})
    assert len(c.events) == before


def test_should_record_runtime_readiness_failure_debounce():
    c = Controller()

    class Validation:
        state = "invalid"

    class Readiness:
        state = "actionable"
        degraded_fields = ("pot",)
        reasons = ("missing_pot",)

    canonical_state = CanonicalTableState(
        spot_id="s",
        street="TURN",
        pot=10.0,
        hero_cards=("Ah", "Kd"),
        board=("As", "Kd", "7h", "2c"),
        legal_actions=(),
        action_buttons=(),
        metadata={"hero_participation": "in_hand"},
    )
    first = c._should_record_runtime_readiness_failure(canonical_state, Validation(), Readiness())
    second = c._should_record_runtime_readiness_failure(canonical_state, Validation(), Readiness())
    assert isinstance(first, bool) and isinstance(second, bool)


def test_build_runtime_failure_crops_uses_selected_regions():
    c = Controller()
    frame = np.full((40, 40, 3), 90, dtype=np.uint8)
    c.last_valid_frame = frame
    c.last_resolved_runtime_state = {
        "metadata": {
            "vision": {
                "region_resolutions": {
                    "pot": {"selected": {"bbox": [5, 5, 15, 15]}},
                    "hero": {"selected": {}},
                }
            }
        }
    }
    crops = c._build_runtime_failure_crops()
    assert set(crops) == {"pot"}
