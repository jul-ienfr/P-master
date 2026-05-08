from src.runtime.evidence_models import (
    CropQualityReport,
    FIELD_CRITICALITY,
    FieldCandidate,
    FieldCriticality,
    FieldEvidence,
    FrameQualityReport,
    RuntimeReadiness,
)


def test_field_criticality_mapping_marks_hero_cards_as_critical():
    assert FIELD_CRITICALITY["hero_cards"] is FieldCriticality.CRITICAL
    assert FIELD_CRITICALITY["player_name"] is FieldCriticality.CONTEXTUAL


def test_field_evidence_serializes_selected_candidate_and_crop_quality():
    candidate = FieldCandidate(field_name="pot", value=1250.0, raw_text="1 250", confidence=0.94, source="ocr")
    crop_quality = CropQualityReport(field_name="pot", width=120, height=40, quality_score=0.88)
    evidence = FieldEvidence(
        field_name="pot",
        criticality=FieldCriticality.IMPORTANT,
        selected_value=1250.0,
        selected_candidate=candidate,
        candidates=(candidate,),
        confidence=0.94,
        crop_quality=crop_quality,
        state="confirmed",
    )

    payload = evidence.to_dict()
    assert payload["selected_value"] == 1250.0
    assert payload["selected_candidate"]["raw_text"] == "1 250"
    assert payload["crop_quality"]["quality_score"] == 0.88
    assert evidence.state_confidence == 0.94


def test_runtime_readiness_exposes_legacy_state_confidence_projection():
    readiness = RuntimeReadiness(
        state="actionable",
        actionable=True,
        score=0.91,
        state_confidence=0.91,
        reasons=("ok",),
    )

    payload = readiness.to_dict()
    assert payload["state"] == "actionable"
    assert payload["state_confidence"] == 0.91


def test_frame_quality_report_to_dict_preserves_rejection_reason():
    report = FrameQualityReport(quality_score=0.25, rejected=True, reject_reason="stale_frame")
    assert report.to_dict()["reject_reason"] == "stale_frame"
