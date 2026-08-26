"""Tests d'intégration du boot SuperBotController (construction réelle, config du dépôt)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.main import SuperBotController, run_bot


@pytest.fixture(scope="module")
def controller():
    return SuperBotController(str(ROOT / "config.json"))


def test_controller_boots_with_repo_config(controller):
    assert controller.is_running is False
    assert controller.runtime_api_port > 0
    assert hasattr(controller, "config")
    assert controller.config  # config du dépôt chargée


def test_operator_snapshot_after_boot(controller):
    snapshot = controller._build_operator_snapshot()
    assert "status" in snapshot
    # le runtime session id est construit au boot et réutilisé
    assert controller.runtime_session_id


def test_wiring_helpers_return_live_objects(controller):
    pipeline = controller._get_frame_pipeline()
    assert pipeline is controller._get_frame_pipeline()  # lazy singleton

    runtime_loop = controller._get_runtime_loop()
    assert runtime_loop is controller._get_runtime_loop()

    classifier = controller._get_button_classifier()
    assert classifier is controller._get_button_classifier()


def test_run_bot_is_importable_entrypoint():
    # l'entrypoint CLI reste câblé sans l'exécuter (boucle infinie)
    assert callable(run_bot)
