"""Canonical replay adapters for external poker research environments."""

from __future__ import annotations

from typing import Any

from poker.decisionmaker.v2_contracts import DecisionSnapshot, ReplayRecord, SpotSnapshot


def spot_to_pokerkit_payload(spot: SpotSnapshot) -> dict[str, Any]:
    return {
        "spot_id": spot.spot_id,
        "street": spot.game_stage.lower(),
        "board": list(spot.board),
        "hero_cards": list(spot.hero_cards),
        "hero_position": spot.hero_position,
        "pot": spot.pot,
        "stack": spot.stack,
        "action_history": list(spot.action_history),
        "legal_actions": list(spot.legal_actions),
        "hero_range": spot.hero_range,
        "villain_ranges": list(spot.villain_ranges),
        "state_confidence": spot.state_confidence,
    }


def spot_to_pypokerengine_payload(spot: SpotSnapshot) -> dict[str, Any]:
    return {
        "uuid": spot.spot_id,
        "round_state": {
            "street": spot.game_stage.lower(),
            "community_card": list(spot.board),
            "pot": {"main": {"amount": spot.pot}},
            "next_player": spot.hero_position,
        },
        "hole_card": list(spot.hero_cards),
        "metadata": {
            "legal_actions": list(spot.legal_actions),
            "hero_range": spot.hero_range,
            "villain_ranges": list(spot.villain_ranges),
        },
    }


def spot_to_rlcard_payload(spot: SpotSnapshot) -> dict[str, Any]:
    return {
        "obs": {
            "board": list(spot.board),
            "hand": list(spot.hero_cards),
            "pot": spot.pot,
            "stack": spot.stack,
        },
        "legal_actions": list(spot.legal_actions),
        "raw_legal_actions": list(spot.legal_actions),
        "raw_obs": {
            "hero_range": spot.hero_range,
            "villain_ranges": list(spot.villain_ranges),
            "action_history": list(spot.action_history),
            "state_confidence": spot.state_confidence,
        },
    }


def spot_to_pokerrl_payload(spot: SpotSnapshot) -> dict[str, Any]:
    return {
        "spot_id": spot.spot_id,
        "street": spot.game_stage.lower(),
        "hero_cards": list(spot.hero_cards),
        "board_cards": list(spot.board),
        "pot": spot.pot,
        "stack": spot.stack,
        "legal_actions": list(spot.legal_actions),
        "metadata": {
            "hero_position": spot.hero_position,
            "hero_range": spot.hero_range,
            "villain_ranges": list(spot.villain_ranges),
            "state_confidence": spot.state_confidence,
        },
    }


def replay_record_from_snapshots(
    replay_id: str,
    spot: SpotSnapshot,
    decision: DecisionSnapshot,
    *,
    result_bb: float = 0.0,
    tags: tuple[str, ...] = (),
) -> ReplayRecord:
    return ReplayRecord(
        replay_id=replay_id,
        spot=spot,
        decision=decision,
        result_metadata={"result_bb": result_bb},
        tags=tags,
    )
