"""Cache Redis optionnel — Phase 3.3

Opt-in via POKER_REDIS_URL. Sans cette variable (ou si le serveur est
injoignable), le cache passe en no-op : get retourne None, set ignore,
aucune exception ne remonte à l'appelant. Le runtime reste 100% fonctionnel
sans Valkey/Redis (fallback mémoire existant inchangé).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AsyncRedisCache:
    def __init__(
        self,
        url: str | None = None,
        *,
        prefix: str = "pkm",
        default_ttl_s: float = 30.0,
        client: Any = None,
    ) -> None:
        self._url = str(url or os.getenv("POKER_REDIS_URL") or "").strip()
        self.prefix = prefix.rstrip(":")
        self.default_ttl_s = float(default_ttl_s or 30.0)
        # Injection pour les tests ; sinon connexion paresseuse au premier usage.
        self._client = client
        self._connection_failed = False
        self._verified = False

    @property
    def enabled(self) -> bool:
        return bool(self._url) and not self._connection_failed

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    async def _ensure_client(self):
        if not self.enabled:
            return None
        if self._client is not None and self._verified:
            return self._client
        try:
            if self._client is None:
                import redis.asyncio as aioredis

                self._client = aioredis.from_url(
                    self._url,
                    decode_responses=True,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.25,
                )
            await self._client.ping()
            self._verified = True
            logger.info("Cache Redis connecté (%s)", self._url)
        except Exception as exc:
            logger.warning("Cache Redis indisponible (%s) — no-op.", exc)
            self._client = None
            self._connection_failed = True
        return self._client

    async def get_json(self, key: str) -> dict | None:
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            raw = await client.get(self._key(key))
            if raw is None:
                return None
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("Cache Redis get échoué (%s): %s", key, exc)
            return None

    async def set_json(self, key: str, value: dict, ttl_s: float | None = None) -> None:
        client = await self._ensure_client()
        if client is None:
            return
        ttl = float(ttl_s if ttl_s is not None else self.default_ttl_s)
        try:
            await client.set(
                self._key(key),
                json.dumps(value, default=str),
                ex=max(1, int(ttl)),
            )
        except Exception as exc:
            logger.debug("Cache Redis set échoué (%s): %s", key, exc)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
