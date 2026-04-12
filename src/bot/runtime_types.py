from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanonicalPlayer:
    seat_id: str
    seat_index: int = -1
    stack: float = 0.0
    name: str = ""
    is_active: bool = True
    has_folded: bool = False
    is_hero: bool = False
    has_button: bool = False
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        return self.name or self.seat_id

    def to_tracker_dict(self) -> dict[str, Any]:
        return {
            "seat_id": self.seat_id,
            "seat_index": self.seat_index,
            "name": self.name,
            "stack": self.stack,
            "active": self.is_active,
            "folded": self.has_folded,
            "is_hero": self.is_hero,
            "has_button": self.has_button,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CanonicalTableState:
    spot_id: str
    street: str
    pot: float
    board: tuple[str, ...] = ()
    hero_cards: tuple[str, ...] = ()
    players: tuple[CanonicalPlayer, ...] = ()
    legal_actions: tuple[str, ...] = ()
    action_buttons: tuple[str, ...] = ()
    state_confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spot_id": self.spot_id,
            "street": self.street,
            "pot": self.pot,
            "board": list(self.board),
            "hero_cards": list(self.hero_cards),
            "players": [player.to_tracker_dict() for player in self.players],
            "legal_actions": list(self.legal_actions),
            "action_buttons": list(self.action_buttons),
            "state_confidence": self.state_confidence,
            "metadata": dict(self.metadata),
        }

    def to_tracker_payload(self) -> dict[str, Any]:
        return self.to_dict()
