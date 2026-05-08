from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass(frozen=True)
class NumericConsensusResult:
    value: Optional[float]
    state: str
    support: int
    history: tuple[float, ...]


class NumericConsensus:
    def __init__(self, history_size: int = 3, tolerance_ratio: float = 0.05) -> None:
        self.history_size = max(2, int(history_size))
        self.tolerance_ratio = max(0.0, float(tolerance_ratio))
        self._history: Deque[float] = deque(maxlen=self.history_size)

    def _is_similar(self, left: float, right: float) -> bool:
        margin = max(abs(left) * self.tolerance_ratio, 0.01)
        return abs(left - right) <= margin

    def update(self, value: Optional[float]) -> NumericConsensusResult:
        if value is None:
            history = tuple(self._history)
            if history:
                return NumericConsensusResult(value=history[-1], state="stale", support=0, history=history)
            return NumericConsensusResult(value=None, state="empty", support=0, history=())

        self._history.append(float(value))
        history = tuple(self._history)
        support = sum(1 for item in history if self._is_similar(item, float(value)))
        threshold = 2 if self.history_size >= 3 else 1
        if support >= threshold:
            return NumericConsensusResult(value=float(value), state="confirmed", support=support, history=history)
        return NumericConsensusResult(value=float(value), state="tentative", support=support, history=history)

    def reset(self) -> None:
        self._history.clear()
