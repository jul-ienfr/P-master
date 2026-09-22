"""Pipeline de décision découplé (Phase 1 — parallélisme vision ↔ décision).

La boucle live (``src/runtime/loop.py``) ne fait plus ``await`` le gate flow :
elle **publie** le snapshot canonique stabilisé dans une ``asyncio.Queue``
(maxsize=1, remplacement) puis continue d'ingérer les frames. Un worker
consomme la requête et exécute le gate flow (lookup blueprint < 5 ms en mode
``POKER_LIVE_LOOKUP_ONLY=1``), pendant que la capture/OCR de la frame
suivante démarre déjà.

Garde-fous d'exécution (Phase 1.3) :
- le worker n'exécute que la requête qui correspond au spot courant
  (``spot_key`` le plus récemment publié) ;
- une requête plus vieille que ``max_decision_age_s`` est écartée
  (``decision_stale``) — jamais de clic sur un spot périmé ;
- le gate flow lui-même re-vérifie le same_spot au moment du clic
  (inchangé, garde existante).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_DECISION_AGE_S = 2.0


@dataclass(slots=True)
class DecisionRequest:
    """Snapshot canonique stabilisé, prêt pour décision."""

    spot_key: str
    enqueued_monotonic: float
    payload: dict[str, Any]


class DecisionScheduler:
    """Producteur/consommateur de requêtes de décision.

    ``run_flow`` est l'async callable du gate flow (les kwargs de la requête).
    ``on_result`` (optionnel, async) reçoit ``(request, flow_result, ms)`` et
    applique les effets de bord de fin de décision (résumés, micro-pause).
    """

    def __init__(
        self,
        run_flow: Callable[..., Awaitable[Any]],
        *,
        max_decision_age_s: float = DEFAULT_MAX_DECISION_AGE_S,
        on_result: Callable[[DecisionRequest, Any, float], Awaitable[None]] | None = None,
    ) -> None:
        self._run_flow = run_flow
        self._on_result = on_result
        self.max_decision_age_s = max(0.1, float(max_decision_age_s))
        self._queue: asyncio.Queue[DecisionRequest] = asyncio.Queue(maxsize=1)
        self._current_spot_key: str | None = None
        self._worker_task: asyncio.Task | None = None
        # --- Métriques (Phase 1.6) ---
        self.published_count = 0
        self.processed_count = 0
        self.skipped_stale_count = 0
        self.skipped_replaced_count = 0
        self.in_flight = False
        self.frames_during_decision = 0
        self.last_end_to_end_ms: float | None = None
        self.last_decision_ms: float | None = None

    # ------------------------------------------------------------ producer
    def publish(self, request: DecisionRequest) -> bool:
        """Publie une requête (remplace toute requête en attente)."""
        self.published_count += 1
        self._current_spot_key = request.spot_key
        if self.in_flight:
            self.frames_during_decision += 1
        try:
            self._queue.get_nowait()
            self.skipped_replaced_count += 1
        except asyncio.QueueEmpty:
            pass
        try:
            self._queue.put_nowait(request)
            return True
        except asyncio.QueueFull:  # défensif : maxsize=1 + drop ci-dessus
            return False

    def current_spot_key(self) -> str | None:
        return self._current_spot_key

    # ------------------------------------------------------------ consumer
    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker_loop(), name="decision-scheduler"
            )

    async def stop(self) -> None:
        task = self._worker_task
        self._worker_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def _worker_loop(self) -> None:
        while True:
            request = await self._queue.get()
            try:
                await self._process(request)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — le worker ne meurt jamais
                logger.error("DecisionScheduler: erreur flow : %s", exc)
            finally:
                self._queue.task_done()

    async def _process(self, request: DecisionRequest) -> None:
        age_s = time.monotonic() - request.enqueued_monotonic
        if request.spot_key != self._current_spot_key:
            # Remplacée par un spot plus récent avant même de démarrer.
            self.skipped_stale_count += 1
            return
        if age_s > self.max_decision_age_s:
            self.skipped_stale_count += 1
            logger.info(
                "DecisionScheduler: requête périmée écartée (%.2fs > %.2fs) — decision_stale.",
                age_s,
                self.max_decision_age_s,
            )
            return
        self.in_flight = True
        started = time.monotonic()
        try:
            flow_result = await self._run_flow(**request.payload)
        finally:
            self.in_flight = False
            self.last_end_to_end_ms = (
                time.monotonic() - request.enqueued_monotonic
            ) * 1000.0
        self.processed_count += 1
        self.last_decision_ms = (time.monotonic() - started) * 1000.0
        if self._on_result is not None and flow_result is not None:
            await self._on_result(request, flow_result, self.last_decision_ms)

    # ------------------------------------------------------------ metrics
    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            "published": self.published_count,
            "processed": self.processed_count,
            "skipped_stale": self.skipped_stale_count,
            "skipped_replaced": self.skipped_replaced_count,
            "in_flight": self.in_flight,
            "frames_during_decision": self.frames_during_decision,
            "end_to_end_ms": self.last_end_to_end_ms,
            "decision_ms": self.last_decision_ms,
        }
