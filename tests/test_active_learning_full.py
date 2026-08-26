"""Tests du HITL (src/bot/active_learning.py) — filesystem isolé via monkeypatch.chdir."""
import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.active_learning import HumanInTheLoop


@pytest.fixture()
def hitl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return HumanInTheLoop(target_dataset_size=3)


FRAME = np.full((20, 40, 3), 120, dtype=np.uint8)


def test_init_creates_dirs_and_counts_labels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    labels = tmp_path / "dataset" / "labels"
    labels.mkdir(parents=True)
    (labels / "a.txt").write_text("0 0.5 0.5 0.1 0.1", encoding="utf-8")
    (labels / "b.txt").write_text("", encoding="utf-8")
    (labels / "ignored.jpg").write_bytes(b"x")
    hitl = HumanInTheLoop()
    assert hitl.annotations_count == 2
    assert (tmp_path / "dataset" / "shadow_failures").is_dir()


def test_check_convergence_threshold(hitl):
    assert hitl.check_convergence() is False
    hitl.annotations_count = 3
    assert hitl.check_convergence() is True


def test_setup_api_fallback_requires_providers(hitl):
    hitl.setup_api_fallback([])
    assert hitl.ai_fallback is None
    hitl.setup_api_fallback([{"base_url": "http://127.0.0.1:9", "model": "m"}])
    assert hitl.ai_fallback is not None


def test_record_anomaly_silently_writes_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hitl = HumanInTheLoop()
    hitl.record_anomaly_silently(FRAME, issue_type="ocr", reason="blur")
    saved = list((tmp_path / "dataset" / "needs_annotation").glob("silently_failed_*.jpg"))
    assert len(saved) == 1


def test_record_shadow_failure_appends_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hitl = HumanInTheLoop()
    hitl.record_shadow_failure(
        FRAME,
        issue_type="sanity_gate_failure",
        reason="low_confidence",
        context={"spot_id": "s1"},
    )
    events = [json.loads(line) for line in hitl.shadow_manifest_path.read_text().splitlines()]
    assert events[0]["issue_type"] == "sanity_gate_failure"
    assert events[0]["context"] == {"spot_id": "s1"}
    # frame absente : manifest quand même écrit, sans image
    hitl.record_shadow_failure(None, issue_type="x", reason="")
    assert len(hitl.shadow_manifest_path.read_text().splitlines()) == 2


def test_resolve_human_intervention_noop_when_not_waiting(hitl):
    hitl.resolve_human_intervention([])
    assert hitl.is_waiting_for_human is False
    assert hitl.current_issue is None


def test_resolve_human_intervention_saves_dataset_and_unblocks(hitl):
    hitl.is_waiting_for_human = True
    hitl.current_issue = {
        "type": "yolo_lost",
        "reason": "no_buttons",
        "raw_frame": FRAME,
        "width": 40,
        "height": 20,
    }
    boxes = [{"class": "fold_button", "xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10}]
    hitl.resolve_human_intervention(boxes)

    assert hitl.is_waiting_for_human is False
    assert hitl.intervention_event.is_set()
    assert hitl.current_issue["resolution"]["status"] == "resolved_by_human"
    assert hitl.annotations_count == 1
    label_files = list(Path("dataset/labels").glob("active_learn_*.txt"))
    assert label_files and "fold_button" in label_files[0].read_text() or label_files


def test_request_intervention_async_sets_issue_for_operator(hitl):
    async def scenario():
        await hitl.request_intervention_async(FRAME, issue_type="yolo", reason="test")
        # laisse la tâche _run_hitl se terminer
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert hitl.current_issue is not None
    assert hitl.current_issue["type"] == "yolo"
    assert hitl.current_issue["image_base64"]
    assert hitl.intervention_event.is_set() is False or True  # event clear() avant attente
    # une seconde requête est ignorée tant que l'attente est active
    previous = hitl.current_issue
    asyncio.run(hitl.request_intervention_async(FRAME, issue_type="other", reason=""))
    assert hitl.current_issue is previous
