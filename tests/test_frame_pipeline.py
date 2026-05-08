from pathlib import Path
import sys
import time
import types

import numpy as np
from copy import deepcopy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.frame_pipeline import FramePipeline
from src.vision.detector import DetectionResult, TableState, build_detection_quality_metadata


def _copy_state_for_test(state):
    model_copy = getattr(state, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    return deepcopy(state)


def test_frame_pipeline_detects_initial_visual_regions_as_changed():
    controller = types.SimpleNamespace(
        _last_visual_previews={},
        _visual_state_change_threshold=0.995,
    )

    def build_preview(frame, bbox):
        return np.ones((4, 4), dtype=np.uint8)

    def is_image_changed(previous, current, threshold=0.0):
        return previous is None or not np.array_equal(previous, current)

    controller._build_visual_preview = build_preview
    controller._is_image_changed = is_image_changed

    pipeline = FramePipeline(controller)
    changed, previews, regions = pipeline._detect_relevant_visual_change(np.zeros((40, 60, 3), dtype=np.uint8))

    assert changed is True
    assert set(previews.keys()) == {"table", "board", "pot", "hero", "actions"}
    assert set(regions) == {"table", "board", "pot", "hero", "actions"}


def test_process_frame_and_convert_state_expose_frame_and_crop_quality_metadata():
    controller = types.SimpleNamespace(
        _last_visual_previews={},
        _visual_state_change_threshold=0.995,
        _last_visual_state_at=0.0,
        _visual_state_refresh_interval_s=0.0,
        _last_visual_state=None,
        last_pot_crop=None,
        last_pot_value=0.0,
        hitl=types.SimpleNamespace(is_waiting_for_human=True),
        detector=types.SimpleNamespace(
            analyze_frame=lambda frame: TableState(
                pots=[DetectionResult(class_name="pot_area", confidence=0.9, bbox=(10, 10, 60, 30))],
                metadata={"table_detected": True, "detector_mode": "template"},
            )
        ),
        amount_ocr=types.SimpleNamespace(
            read_and_parse_amount=lambda crop: 42.0,
            get_metadata=lambda: {"loaded_engines": ["rapidocr"]},
        ),
        ocr=types.SimpleNamespace(
            get_metadata=lambda: {
                "loaded_engines": ["rapidocr"],
                "requested_engines": ["rapidocr"],
                "mode": "fallback",
                "parallel": False,
            }
        ),
        _label_generic_action_buttons=lambda state, frame: state,
        _build_visual_preview=lambda frame, bbox: np.ones((4, 4), dtype=np.uint8),
        _is_image_changed=lambda previous, current, threshold=0.0: previous is None or not np.array_equal(previous, current),
        _copy_table_state=_copy_state_for_test,
        _set_loop_stage=lambda *args, **kwargs: None,
        _stabilize_runtime_hero_cards=lambda hero_cards, board, state: hero_cards,
        _build_players=lambda state, frame: [],
        _derive_legal_actions=lambda state: ((), ()),
        _normalize_auxiliary_action_state=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _derive_runtime_street=lambda board, hero_cards, action_buttons: "IDLE",
        _normalize_board_for_street=lambda board, street: board,
        _smooth_legal_actions=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _smooth_runtime_state_confidence=lambda confidence, street, board, hero_cards: confidence,
        _derive_hero_participation_mode=lambda board, hero_cards, pot, action_buttons: "waiting_next_hand",
        _extract_actionable_runtime_buttons=lambda action_buttons: (),
    )

    pipeline = FramePipeline(controller)
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, ::2] = 255
    frame[:, ::2] = 255

    import asyncio

    state = asyncio.run(pipeline._process_frame(frame))
    assert "frame_quality" in state.metadata
    assert "crop_quality" in state.metadata
    assert "pot" in state.metadata["crop_quality"]
    assert "runtime_geometry" in state.metadata
    assert "region_proposals" in state.metadata
    assert "region_resolutions" in state.metadata
    assert "detection_quality" in state.metadata
    assert "pot" in state.metadata["region_proposals"]
    assert state.metadata["region_resolutions"]["pot"]["selected"]["source"] in {"detector_pot", "preset_geometry"}
    assert "pots" in state.metadata["detection_quality"]

    canonical = pipeline._convert_state_for_tracker(state, frame)
    assert canonical.metadata["vision"]["frame_quality"]["quality_score"] >= 0.0
    assert canonical.metadata["vision"]["crop_quality"]["pot"]["field_name"] == "pot"
    assert canonical.metadata["vision"]["runtime_geometry"]["source"]
    assert canonical.metadata["vision"]["region_proposals"]["pot"]
    assert canonical.metadata["vision"]["region_resolutions"]["pot"]["selected"]
    assert "pots" in canonical.metadata["vision"]["detection_quality"]
    assert canonical.metadata["vision"]["numeric_reader"]["pot"]["selected_value"] == 42.0
    assert canonical.metadata["vision"]["visual_changed"] is True


def test_detection_quality_scores_in_region_above_out_of_region():
    pixel_regions = {
        "board": (20, 20, 80, 50),
        "hero": (20, 60, 80, 95),
        "pot": (35, 38, 65, 55),
        "actions": (70, 70, 120, 100),
        "table": (0, 0, 140, 110),
    }
    inside_state = TableState(
        board_cards=[DetectionResult(class_name="As", confidence=0.9, bbox=(36, 22, 52, 46))]
    )
    outside_state = TableState(
        board_cards=[DetectionResult(class_name="As", confidence=0.9, bbox=(100, 80, 116, 104))]
    )

    inside_quality = build_detection_quality_metadata(inside_state, pixel_regions)
    outside_quality = build_detection_quality_metadata(outside_state, pixel_regions)

    inside_score = inside_quality["board_cards"]["detections"][0]["score"]
    outside_score = outside_quality["board_cards"]["detections"][0]["score"]
    assert inside_score > outside_score



def test_process_frame_reads_pot_from_geometry_when_detector_misses_pot():
    hitl_calls = []
    controller = types.SimpleNamespace(
        _last_visual_previews={},
        _visual_state_change_threshold=0.995,
        _last_visual_state_at=0.0,
        _visual_state_refresh_interval_s=0.0,
        _last_visual_state=None,
        last_pot_crop=None,
        last_pot_value=0.0,
        hitl=types.SimpleNamespace(
            is_waiting_for_human=False,
            request_intervention_async=lambda **kwargs: hitl_calls.append(kwargs),
        ),
        detector=types.SimpleNamespace(
            analyze_frame=lambda frame: TableState(
                board_cards=[
                    DetectionResult(class_name="board_card", confidence=0.9, bbox=(20, 10, 30, 30)),
                    DetectionResult(class_name="board_card", confidence=0.9, bbox=(32, 10, 42, 30)),
                    DetectionResult(class_name="board_card", confidence=0.9, bbox=(44, 10, 54, 30)),
                ],
                metadata={"table_detected": True, "detector_mode": "template"},
            )
        ),
        amount_ocr=types.SimpleNamespace(
            read_and_parse_amount=lambda crop: 43.0,
            get_metadata=lambda: {"loaded_engines": ["rapidocr"], "selected_text": "43 389"},
        ),
        ocr=types.SimpleNamespace(
            get_metadata=lambda: {
                "loaded_engines": ["rapidocr"],
                "requested_engines": ["rapidocr"],
                "mode": "fallback",
                "parallel": False,
            }
        ),
        _label_generic_action_buttons=lambda state, frame: state,
        _build_visual_preview=lambda frame, bbox: np.ones((4, 4), dtype=np.uint8),
        _is_image_changed=lambda previous, current, threshold=0.0: previous is None or not np.array_equal(previous, current),
        _copy_table_state=_copy_state_for_test,
        _set_loop_stage=lambda *args, **kwargs: None,
        _stabilize_runtime_hero_cards=lambda hero_cards, board, state: hero_cards,
        _build_players=lambda state, frame: [],
        _derive_legal_actions=lambda state: ((), ()),
        _normalize_auxiliary_action_state=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _derive_runtime_street=lambda board, hero_cards, action_buttons: "FLOP",
        _normalize_board_for_street=lambda board, street: board,
        _smooth_legal_actions=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _smooth_runtime_state_confidence=lambda confidence, street, board, hero_cards: confidence,
        _derive_hero_participation_mode=lambda board, hero_cards, pot, action_buttons: "observing_hand",
        _extract_actionable_runtime_buttons=lambda action_buttons: (),
    )

    pipeline = FramePipeline(controller)
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, ::2] = 255

    import asyncio

    state = asyncio.run(pipeline._process_frame(frame))

    assert state.pots
    assert state.pots[0].confidence == 43389.0
    assert state.metadata["numeric_reader"]["pot"]["selected_value"] == 43389.0
    assert state.metadata["numeric_reader"]["pot"]["ocr_without_detector"] is True
    assert len(state.metadata["numeric_reader"]["pot"]["ocr_bbox"]) == 4
    assert state.metadata["numeric_reader"]["pot"]["ocr_focus"] in {"top_label", "full_region"}
    assert hitl_calls == []


def test_process_frame_updates_fast_lane_pot_even_when_visual_state_is_reused():
    cached_state = TableState(
        pots=[DetectionResult(class_name="pot_area", confidence=3402.0, bbox=(40, 20, 80, 40))],
        metadata={
            "runtime_geometry": {
                "regions": {
                    "pot": [30.0, 10.0, 90.0, 50.0],
                }
            }
        },
    )
    controller = types.SimpleNamespace(
        _last_visual_previews={"pot": np.ones((4, 4), dtype=np.uint8)},
        _visual_state_change_threshold=0.995,
        _last_visual_state_at=time.monotonic(),
        _visual_state_refresh_interval_s=999.0,
        _last_visual_state=cached_state,
        _copy_table_state=_copy_state_for_test,
        _detect_relevant_visual_change=lambda frame: (False, {"pot": np.ones((4, 4), dtype=np.uint8)}, ()),
        _set_loop_stage=lambda *args, **kwargs: None,
        amount_ocr=types.SimpleNamespace(
            read_and_parse_amount=lambda crop: 3602.0,
            get_metadata=lambda: {"selected_text": "Pot : 3 602", "selected_confidence": 0.95},
        ),
    )

    pipeline = FramePipeline(controller)
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, ::2] = 255

    import asyncio

    state = asyncio.run(pipeline._process_frame(frame))

    assert state.pots[0].confidence == 3602.0
    assert state.metadata["observed_pot_fast"]["value"] == 3602.0


def test_convert_state_uses_raw_board_count_to_escape_idle_when_board_cards_are_visible():
    controller = types.SimpleNamespace(
        _label_generic_action_buttons=lambda state, frame: state,
        _stabilize_runtime_hero_cards=lambda hero_cards, board, state: hero_cards,
        _build_players=lambda state, frame: [],
        _derive_legal_actions=lambda state: ((), ()),
        _normalize_auxiliary_action_state=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _derive_runtime_street=lambda board, hero_cards, action_buttons: "IDLE",
        _normalize_board_for_street=lambda board, street: board,
        _smooth_legal_actions=lambda legal_actions, action_buttons, board, hero_cards: (legal_actions, action_buttons),
        _smooth_runtime_state_confidence=lambda confidence, street, board, hero_cards: confidence,
        _derive_hero_participation_mode=lambda board, hero_cards, pot, action_buttons: "observing_hand",
        _extract_actionable_runtime_buttons=lambda action_buttons: (),
        ocr=types.SimpleNamespace(get_metadata=lambda: {}),
    )

    pipeline = FramePipeline(controller)
    state = TableState(
        board_cards=[
            DetectionResult(class_name="board_card", confidence=0.8, bbox=(10, 10, 20, 20)),
            DetectionResult(class_name="board_card", confidence=0.8, bbox=(22, 10, 32, 20)),
            DetectionResult(class_name="board_card", confidence=0.8, bbox=(34, 10, 44, 20)),
        ],
        metadata={"table_detected": True},
    )
    frame = np.zeros((60, 100, 3), dtype=np.uint8)

    canonical = pipeline._convert_state_for_tracker(state, frame)

    assert canonical.street == "FLOP"
    assert canonical.metadata["vision"]["raw_board_count"] == 3
    assert canonical.metadata["observation_street"] == "FLOP"
