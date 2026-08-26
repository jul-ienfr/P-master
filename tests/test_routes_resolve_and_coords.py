"""Tests complémentaires : /resolve (branches d'erreur) et diagnostics de coordonnées."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.routes_resolve import ResolveRoutesMixin
from src.bot.state_resolver import StateResolverMixin
from src.vision.models import TableState


class FakeQueryRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class Api(ResolveRoutesMixin):
    def __init__(self, hitl):
        self.hitl = hitl


def run(coro):
    return asyncio.run(coro)


def test_handle_resolve_rejects_empty_boxes():
    api = Api(hitl=None)
    response = run(api.handle_resolve(FakeQueryRequest({"boxes": []})))
    assert response.status == 400
    assert "boîte" in json.loads(response.text)["error"]


def test_handle_resolve_rejects_when_bot_not_waiting():
    class Hitl:
        is_waiting_for_human = False

        def resolve_human_intervention(self, boxes):
            raise AssertionError("ne doit pas être appelé")

    api = Api(hitl=Hitl())
    response = run(api.handle_resolve(FakeQueryRequest({"boxes": [1, 2]})))
    assert response.status == 400


def test_handle_resolve_success_delegates_to_hitl():
    received = []

    class Hitl:
        is_waiting_for_human = True

        def resolve_human_intervention(self, boxes):
            received.append(list(boxes))

    api = Api(hitl=Hitl())
    response = run(api.handle_resolve(FakeQueryRequest({"boxes": [5]})))
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["success"] is True
    assert received == [[5]]


def test_handle_resolve_internal_error_returns_500():
    class Hitl:
        is_waiting_for_human = True

        def resolve_human_intervention(self, boxes):
            raise RuntimeError("boom")

    api = Api(hitl=Hitl())
    response = run(api.handle_resolve(FakeQueryRequest({"boxes": [1]})))
    assert response.status == 500
    assert json.loads(response.text)["error"] == "boom"


def test_get_action_coord_diagnostic_defaults_and_slot_boxes():
    class Resolver(StateResolverMixin):
        pass

    resolver = Resolver()
    state = TableState(
        metadata={
            "dynamic_coord_diagnostics": {"FOLD": {"source": "detected_button"}},
            "button_slot_boxes": {"CALL": (1, 2, 3, 4)},
        }
    )
    diag = resolver._get_action_coord_diagnostic(state, "fold")
    assert diag["coord_key"] == "FOLD"
    assert diag["source"] == "detected_button"
    assert diag["slot_boxes"] == {"CALL": (1, 2, 3, 4)}

    # action sans diagnostic : valeurs par défaut uniquement
    empty = resolver._get_action_coord_diagnostic(TableState(metadata={}), "bet_box")
    assert empty["coord_key"] == "BET_BOX"
    assert empty["slot_boxes"] == {}
