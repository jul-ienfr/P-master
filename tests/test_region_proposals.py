from src.vision.region_proposals import RegionProposal, resolve_region_proposals


def test_region_resolver_prefers_higher_score_proposal():
    proposals = {
        "pot": [
            RegionProposal(field_name="pot", bbox=(1, 1, 10, 10), source="preset_geometry", score=0.85),
            RegionProposal(field_name="pot", bbox=(2, 2, 11, 11), source="detector_pot", score=0.95),
        ]
    }

    resolved = resolve_region_proposals(proposals)

    assert resolved["pot"].selected.source == "detector_pot"


def test_region_resolver_uses_source_priority_as_tie_breaker():
    proposals = {
        "actions": [
            RegionProposal(field_name="actions", bbox=(1, 1, 10, 10), source="preset_geometry", score=0.9),
            RegionProposal(field_name="actions", bbox=(2, 2, 11, 11), source="detector_action_buttons", score=0.9),
        ]
    }

    resolved = resolve_region_proposals(proposals)

    assert resolved["actions"].selected.source == "detector_action_buttons"
