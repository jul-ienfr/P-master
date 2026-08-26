"""Tests P0.9 — agrégation qualité vision + incidents dédiés."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.vision.quality_aggregator import VisionQualityAggregator


def test_aggregator_counts_detection_and_crop_samples():
    agg = VisionQualityAggregator(rejection_incident_threshold=3, incident_callback=lambda *a, **k: None)

    agg.observe(
        {
            "hero_cards": {"count": 2, "average_score": 0.9},
            "board_cards": {"count": 0, "average_score": 0.0},
        },
        {"pot": {"rejected": False, "quality_score": 0.8}},
    )
    agg.observe(
        {"hero_cards": {"count": 2, "average_score": 0.8}},
        {"pot": {"rejected": True, "quality_score": 0.05}},
    )

    snap = agg.snapshot()
    assert snap["detection:hero_cards"]["samples"] == 2
    assert snap["detection:hero_cards"]["seen"] == 2
    assert snap["detection:board_cards"]["seen"] == 0
    assert snap["crop:pot"]["consecutive_rejected"] == 1


def test_aggregator_emits_single_incident_on_sustained_rejection():
    incidents = []
    agg = VisionQualityAggregator(
        rejection_incident_threshold=3,
        incident_callback=lambda code, severity="warning", **ctx: incidents.append((code, ctx)),
    )

    for _ in range(5):
        agg.observe({}, {"pot": {"rejected": True, "quality_score": 0.0}})

    pot = agg.snapshot()["crop:pot"]
    assert pot["consecutive_rejected"] == 5
    assert len(incidents) == 1  # un seul incident jusqu'à récupération
    assert incidents[0][0] == "vision_quality_degraded"
    assert incidents[0][1]["element"] == "crop:pot"


def test_aggregator_resets_after_recovery():
    incidents = []
    agg = VisionQualityAggregator(
        rejection_incident_threshold=2,
        incident_callback=lambda code, severity="warning", **ctx: incidents.append(code),
    )

    for _ in range(3):
        agg.observe({}, {"pot": {"rejected": True, "quality_score": 0.0}})
    agg.observe({}, {"pot": {"rejected": False, "quality_score": 0.9}})
    for _ in range(3):
        agg.observe({}, {"pot": {"rejected": True, "quality_score": 0.0}})

    assert len(incidents) == 2  # re-déclenchement après récupération
