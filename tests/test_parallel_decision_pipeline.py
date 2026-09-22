"""Validation plan 4 — pipeline de décision parallèle (Phase 1).

- Un solve lent (mock 800 ms) n'empêche pas l'ingestion de frames : les
  publications suivantes continuent pendant le traitement.
- Jamais de décision exécutée sur un spot périmé (spot_key ≠ courant, ou
  requête trop vieille).
- Sémantique de remplacement : seule la requête la plus récente du spot
  courant est traitée.
"""

from __future__ import annotations

import asyncio
import time

from src.runtime.decision_pipeline import (
    DEFAULT_MAX_DECISION_AGE_S,
    DecisionRequest,
    DecisionScheduler,
)


def _request(spot_key: str, *, age: float = 0.0, **payload) -> DecisionRequest:
    return DecisionRequest(
        spot_key=spot_key,
        enqueued_monotonic=time.monotonic() - age,
        payload=payload,
    )


def test_frames_continue_ingesting_during_slow_solve():
    """Solve mocké à 800 ms ⇒ les frames suivantes sont ingérées pendant."""
    processed: list[str] = []

    async def slow_flow(**kwargs) -> dict:
        await asyncio.sleep(0.8)
        processed.append(kwargs["tag"])
        return {"ok": True}

    async def scenario() -> DecisionScheduler:
        scheduler = DecisionScheduler(slow_flow)
        scheduler.start()
        try:
            scheduler.publish(_request("spotA", tag="A1"))
            # Attendre que le worker ait pris la requête (in_flight).
            for _ in range(100):
                if scheduler.in_flight:
                    break
                await asyncio.sleep(0.01)
            assert scheduler.in_flight
            # ≥3 "frames" publiées pendant que le solve tourne.
            for index in range(3):
                scheduler.publish(_request("spotA", tag=f"A{index + 2}"))
                await asyncio.sleep(0.05)
            assert scheduler.frames_during_decision >= 3
            for _ in range(200):
                if scheduler.processed_count >= 1:
                    break
                await asyncio.sleep(0.01)
            assert scheduler.processed_count >= 1
        finally:
            await scheduler.stop()
        return scheduler

    asyncio.run(scenario())
    assert len(processed) >= 1
    assert "A1" in processed


def test_never_processes_stale_spot_key():
    """Une requête remplacée par un spot plus récent n'est jamais exécutée."""
    processed: list[str] = []

    async def fast_flow(**kwargs) -> dict:
        processed.append(kwargs["tag"])
        return {"ok": True}

    async def scenario() -> None:
        scheduler = DecisionScheduler(fast_flow)
        scheduler.start()
        try:
            scheduler.publish(_request("spotOLD", tag="old"))
            # Éviction immédiate par le spot courant (queue maxsize=1).
            scheduler.publish(_request("spotNEW", tag="new"))
            for _ in range(100):
                if scheduler.processed_count + scheduler.skipped_stale_count >= 1:
                    break
                await asyncio.sleep(0.01)
        finally:
            await scheduler.stop()
        assert "old" not in processed

    asyncio.run(scenario())


def test_aged_request_is_refused_as_decision_stale():
    """Une requête plus vieille que le seuil est écartée (jamais de clic)."""
    processed: list[str] = []

    async def flow(**kwargs) -> dict:
        processed.append(kwargs["tag"])
        return {"ok": True}

    async def scenario() -> None:
        scheduler = DecisionScheduler(flow, max_decision_age_s=0.2)
        scheduler.start()
        try:
            scheduler.publish(_request("spotX", tag="aged", age=DEFAULT_MAX_DECISION_AGE_S + 5.0))
            for _ in range(100):
                if scheduler.skipped_stale_count >= 1:
                    break
                await asyncio.sleep(0.01)
            assert scheduler.processed_count == 0
            assert scheduler.skipped_stale_count >= 1
        finally:
            await scheduler.stop()

    asyncio.run(scenario())
    assert "aged" not in processed


def test_end_to_end_metric_is_recorded():
    async def flow(**kwargs) -> dict:
        await asyncio.sleep(0.05)
        return {"ok": True}

    async def scenario() -> DecisionScheduler:
        scheduler = DecisionScheduler(flow)
        scheduler.start()
        try:
            scheduler.publish(_request("spotZ", tag="z"))
            for _ in range(100):
                if scheduler.processed_count >= 1:
                    break
                await asyncio.sleep(0.01)
            assert scheduler.last_end_to_end_ms is not None
            assert scheduler.last_end_to_end_ms >= 40.0
            assert scheduler.last_decision_ms is not None
        finally:
            await scheduler.stop()
        return scheduler

    scheduler = asyncio.run(scenario())
    metrics = scheduler.metrics_snapshot()
    assert metrics["published"] == 1
    assert metrics["processed"] == 1
