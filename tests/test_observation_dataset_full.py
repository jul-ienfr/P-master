# -*- coding: utf-8 -*-
"""Tests du collecteur de dataset d'observation (src/vision/observation_dataset.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.runtime_types import CanonicalTableState
from src.vision.models import TableState
from src.vision.observation_dataset import ObservationDatasetCollector


@pytest.fixture()
def collector(tmp_path):
    return ObservationDatasetCollector(
        enabled=True,
        dataset_dir=str(tmp_path / "obs"),
        capture_interval_s=0.5,
        require_visual_change=True,
        max_samples_per_session=10,
    )


def observing_state(**overrides):
    base = dict(
        spot_id="live:IDLE:obs",
        street="PREFLOP",
        pot=12.5,
        hero_cards=(),
        board=(),
        legal_actions=(),
        action_buttons=("resume_hand",),
        metadata={"hero_participation": "waiting_next_hand"},
    )
    base.update(overrides)
    return CanonicalTableState(**base)


def test_snapshot_reports_counts(collector):
    snap = collector.snapshot()
    assert snap["enabled"] is True
    assert snap["captured_samples"] == 0
    assert (collector.dataset_root / "dataset.yaml").is_file()


def test_maybe_capture_writes_image_and_manifest(collector):
    frame = np.full((60, 120, 3), 90, dtype=np.uint8)
    detector_state = TableState(metadata={"visual_changed": True})
    path = collector.maybe_capture(frame, observing_state(), detector_state)
    assert path is not None and path.is_file()
    lines = collector.manifest_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["hero_participation"] == "waiting_next_hand"
    assert collector._captured_samples >= 1
    # second capture identique -> dédupliquée
    assert collector.maybe_capture(frame, observing_state(), detector_state) is None


def test_maybe_capture_disabled_or_empty_frame_returns_none(collector):
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    collector.enabled = False
    assert collector.maybe_capture(frame, observing_state()) is None
    collector.enabled = True
    assert collector.maybe_capture(None, observing_state()) is None


def test_maybe_capture_skips_active_hands(collector):
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    active = observing_state(hero_cards=("Ah", "Kd"))
    assert collector.maybe_capture(frame, active) is None
    actionable = observing_state(legal_actions=("CHECK",))
    assert collector.maybe_capture(frame, actionable) is None


def test_maybe_capture_rejects_unknown_participation(collector):
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    idle = observing_state(metadata={"hero_participation": "idle"})
    assert collector.maybe_capture(frame, idle) is None


def test_maybe_capture_respects_visual_change_requirement(collector):
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    reused = TableState(metadata={"reused_visual_state": True, "visual_changed": True})
    assert collector.maybe_capture(frame, observing_state(), reused) is None
    unchanged = TableState(metadata={"visual_changed": False})
    assert collector.maybe_capture(frame, observing_state(), unchanged) is None
    # régions changées sans zone utile -> rejeté
    useless = TableState(
        metadata={"visual_changed": True, "visual_changed_regions": ["chat"]}
    )
    assert collector.maybe_capture(frame, observing_state(), useless) is None
    # région utile -> accepté
    useful = TableState(
        metadata={"visual_changed": True, "visual_changed_regions": ["pot"]}
    )
    assert collector.maybe_capture(frame, observing_state(), useful) is not None


def test_maybe_capture_requires_meaningful_context(collector):
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    empty = CanonicalTableState(
        spot_id="x",
        street="IDLE",
        pot=0.0,
        hero_cards=(),
        board=(),
        legal_actions=(),
        action_buttons=("fold_button",),
        metadata={"hero_participation": "observing_hand"},
    )
    assert collector.maybe_capture(frame, empty) is None


def test_maybe_capture_throttles_rapid_calls(collector):
    collector.capture_interval_s = 3600.0
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    first = collector.maybe_capture(frame, observing_state())
    assert first is not None
    second = collector.maybe_capture(np.ones((30, 30, 3), dtype=np.uint8), observing_state(pot=99.0))
    assert second is None


def test_max_samples_per_session_cap(collector):
    collector.max_samples_per_session = 1
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    state = observing_state()
    assert collector.maybe_capture(frame, state) is not None
    # au-delà du cap : plus rien même avec un état différent
    assert (
        collector.maybe_capture(
            np.ones((30, 30, 3), dtype=np.uint8),
            observing_state(pot=77.0, action_buttons=("im_back",)),
        )
        is None
    )


def test_count_files_filters_by_suffix(collector, tmp_path):
    target = tmp_path / "scan"
    target.mkdir()
    (target / "a.jpg").write_bytes(b"x")
    (target / "b.PNG").write_bytes(b"x")
    (target / "c.txt").write_bytes(b"x")
    assert ObservationDatasetCollector._count_files(target) == 2
    assert ObservationDatasetCollector._count_files(target, suffixes={".txt"}) == 1
    assert ObservationDatasetCollector._count_files(tmp_path / "missing") == 0


def test_frame_digest_is_stable_and_discriminates(collector):
    a = collector._frame_digest(np.zeros((32, 48, 3), dtype=np.uint8))
    b = collector._frame_digest(np.full((32, 48, 3), 200, dtype=np.uint8))
    assert a != b
    assert a == collector._frame_digest(np.zeros((32, 48, 3), dtype=np.uint8))
