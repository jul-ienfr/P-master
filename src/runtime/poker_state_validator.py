from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.bot.runtime_types import CanonicalTableState


@dataclass(frozen=True)
class PokerStateValidationResult:
    state: str
    reasons: tuple[str, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


class PokerStateValidator:
    def validate(self, canonical_state: CanonicalTableState) -> PokerStateValidationResult:
        reasons: list[str] = []
        board = tuple(canonical_state.board or ())
        hero_cards = tuple(canonical_state.hero_cards or ())
        legal_actions = tuple(canonical_state.legal_actions or ())
        pot = float(canonical_state.pot or 0.0)
        street = str(canonical_state.street or "IDLE")

        if len(board) not in (0, 3, 4, 5):
            reasons.append("board_count_invalid")

        expected_street = {0: "PREFLOP", 3: "FLOP", 4: "TURN", 5: "RIVER"}.get(len(board))
        if expected_street and street not in {expected_street, "SHOWDOWN", "IDLE"}:
            reasons.append("street_board_mismatch")

        if hero_cards and len(hero_cards) != 2:
            reasons.append("hero_cards_unconfirmed")

        if board and pot <= 0.0:
            reasons.append("missing_postflop_pot")

        if pot < 0.0:
            reasons.append("negative_pot")

        if legal_actions and not canonical_state.action_buttons:
            reasons.append("legal_actions_without_buttons")

        if any(reason in {"board_count_invalid", "street_board_mismatch", "hero_cards_unconfirmed", "negative_pot"} for reason in reasons):
            state = "hard_invalid"
        elif reasons:
            state = "soft_invalid"
        elif float(canonical_state.state_confidence or 0.0) < 0.6:
            state = "degraded_valid"
        else:
            state = "fully_valid"

        return PokerStateValidationResult(
            state=state,
            reasons=tuple(reasons),
            metadata={
                "street": street,
                "board_count": len(board),
                "hero_cards_count": len(hero_cards),
                "pot": pot,
                "legal_action_count": len(legal_actions),
            },
        )
