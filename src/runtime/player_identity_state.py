from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PlayerIdentityState:
    identities: Dict[str, dict] = field(default_factory=dict)

    def update(self, seat_id: str, resolved_name: str, resolution_source: str) -> dict:
        entry = dict(self.identities.get(seat_id) or {})
        previous_name = str(entry.get("confirmed_name") or "")
        if resolved_name:
            support = int(entry.get("support", 0) or 0) + 1 if previous_name == resolved_name else 1
            state = "confirmed" if support >= 2 else "tentative"
            entry.update(
                {
                    "seat_id": seat_id,
                    "confirmed_name": resolved_name,
                    "support": support,
                    "state": state,
                    "resolution_source": resolution_source,
                }
            )
        else:
            entry.update(
                {
                    "seat_id": seat_id,
                    "state": "stale_confirmed" if previous_name else "unknown",
                    "resolution_source": resolution_source,
                }
            )
        self.identities[seat_id] = entry
        return dict(entry)
