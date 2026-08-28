"""Scheduler de tours multi-table (Phase 1, étapes 14-15).

Boucle asyncio unique itérant les sessions avec un budget temps global.
Priorité : notre tour détecté > timebank imminent > rafraîchissement idle.
Les actions sont exécutées via une file globale sérialisée (une seule table
au premier plan à la fois, délais anti-pattern entre deux tables).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PRIORITY_IDLE_REFRESH = 0
PRIORITY_TIMEBANK_IMMINENT = 50
PRIORITY_OUR_TURN = 100


@dataclass
class SessionTurnSignal:
    """Signal synthétique d'urgence pour une session (produit par le handler)."""

    is_our_turn: bool = False
    timebank_imminent: bool = False
    seconds_since_refresh: float = 0.0

    def priority(self) -> int:
        if self.is_our_turn:
            return PRIORITY_OUR_TURN
        if self.timebank_imminent:
            return PRIORITY_TIMEBANK_IMMINENT
        return PRIORITY_IDLE_REFRESH


class ActionExecutionQueue:
    """File d'exécution globale : une action à la fois, gap minimum humain."""

    def __init__(self, *, min_gap_s: float = 0.35):
        self.min_gap_s = max(0.0, float(min_gap_s))
        self._lock = asyncio.Lock()
        self._last_action_monotonic: float = 0.0
        self.executed_count = 0

    async def submit(
        self,
        action_factory: Callable[[], Awaitable[Any]],
        *,
        min_gap_s: float | None = None,
    ) -> Any:
        gap = self.min_gap_s if min_gap_s is None else max(0.0, float(min_gap_s))
        async with self._lock:
            elapsed = time.monotonic() - self._last_action_monotonic
            remaining = gap - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            try:
                return await action_factory()
            finally:
                self._last_action_monotonic = time.monotonic()
                self.executed_count += 1

    @property
    def busy(self) -> bool:
        return self._lock.locked()


@dataclass
class CycleReport:
    sessions_seen: int = 0
    sessions_processed: int = 0
    budget_exhausted: bool = False
    priorities: dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0.0


class MultiTableLoop:
    """Itère les sessions par priorité décroissante dans un budget temps global."""

    def __init__(
        self,
        manager,
        *,
        signal_provider: Callable[[Any], SessionTurnSignal] | None = None,
        session_handler: Callable[[Any], Awaitable[None]] | None = None,
        execution_queue: ActionExecutionQueue | None = None,
        cycle_budget_ms: float = 1000.0,
        min_cycle_sleep_s: float = 0.01,
    ):
        self.manager = manager
        self.signal_provider = signal_provider or (lambda _session: SessionTurnSignal())
        self.session_handler = session_handler
        self.execution_queue = execution_queue or ActionExecutionQueue()
        self.cycle_budget_ms = max(1.0, float(cycle_budget_ms))
        self.min_cycle_sleep_s = max(0.0, float(min_cycle_sleep_s))

    def ordered_sessions(self, signals: dict[str, SessionTurnSignal]) -> list[tuple[Any, int]]:
        ordered = []
        for session in self.manager.active_sessions:
            signal = signals.get(session.session_id) or SessionTurnSignal()
            priority = signal.priority()
            session.priority = priority
            ordered.append((session, priority))
        ordered.sort(key=lambda item: item[1], reverse=True)
        return ordered

    async def run_cycle(self) -> CycleReport:
        started_at = time.monotonic()
        report = CycleReport()
        refresh = self.manager.refresh()
        if not refresh.get("skipped"):
            logger.debug("Multi-table refresh: %s", refresh)

        signals: dict[str, SessionTurnSignal] = {}
        for session in self.manager.active_sessions:
            try:
                signals[session.session_id] = self.signal_provider(session)
            except Exception:
                signals[session.session_id] = SessionTurnSignal()

        report.sessions_seen = len(self.manager.active_sessions)
        for session, priority in self.ordered_sessions(signals):
            report.priorities[session.session_id] = priority
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            if elapsed_ms >= self.cycle_budget_ms:
                report.budget_exhausted = True
                break
            # Les tours prioritaires passent même si le budget est consommé ;
            # seuls les rafraîchissements idle sont sacrifiés au budget.
            if priority <= PRIORITY_TIMEBANK_IMMINENT and report.budget_exhausted:
                break
            if self.session_handler is None:
                continue
            try:
                await self.session_handler(session)
                report.sessions_processed += 1
            except Exception as exc:
                logger.error("TABLE_HANDLER_ERROR | id=%s error=%s", session.session_id, exc)
                session.record_incident("multi_table_handler_error", error=str(exc))
                report.sessions_processed += 1

        report.duration_ms = round((time.monotonic() - started_at) * 1000.0, 2)
        return report

    async def run(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        while should_stop is None or not should_stop():
            report = await self.run_cycle()
            sleep_s = self.min_cycle_sleep_s
            if report.budget_exhausted:
                sleep_s = max(sleep_s, 0.05)
            await asyncio.sleep(sleep_s)
