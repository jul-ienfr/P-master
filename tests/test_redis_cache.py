"""Tests Phase 3.3 — cache Redis optionnel (profil L2)."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker
from src.data.redis_cache import AsyncRedisCache


class FakeRedisClient:
    def __init__(self, store=None):
        self.store = store if store is not None else {}
        self.pinged = False
        self.closed = False

    async def ping(self):
        self.pinged = True

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def aclose(self):
        self.closed = True


class BrokenRedisClient:
    async def ping(self):
        raise ConnectionError("down")

    async def get(self, key):
        raise ConnectionError("down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("down")


class FakeDB:
    is_available = True

    def __init__(self, profile=None):
        self.profile = profile
        self.fetches = 0

    async def get_player_profile(self, villain_name):
        self.fetches += 1
        return self.profile


def _cache_with(client):
    return AsyncRedisCache(url="redis://localhost:6379/0", client=client)


@pytest.fixture(autouse=True)
def _no_env_url(monkeypatch):
    monkeypatch.delenv("POKER_REDIS_URL", raising=False)


def test_disabled_without_url_is_noop():
    cache = AsyncRedisCache()

    assert cache.enabled is False
    assert asyncio.run(cache.get_json("profile:x")) is None
    asyncio.run(cache.set_json("profile:x", {"a": 1}))  # ne doit pas lever


def test_roundtrip_json():
    client = FakeRedisClient()
    cache = _cache_with(client)

    asyncio.run(cache.set_json("profile:Bob", {"vpip": 0.3}, ttl_s=10))
    assert client.store
    assert asyncio.run(cache.get_json("profile:Bob")) == {"vpip": 0.3}
    assert asyncio.run(cache.get_json("profile:missing")) is None


def test_connection_failure_switches_to_noop():
    cache = _cache_with(BrokenRedisClient())

    assert asyncio.run(cache.get_json("profile:Bob")) is None
    asyncio.run(cache.set_json("profile:Bob", {"a": 1}))
    assert cache.enabled is False
    # Les appels suivants n'essayent plus la connexion.
    assert asyncio.run(cache.get_json("profile:Bob")) is None


def test_profile_l2_hit_avoids_db_fetch(monkeypatch):
    client = FakeRedisClient(
        {"pkm:profile:Villain": '{"player_type": "Nit", "derived_profile": {"style": "Nit"}}'}
    )
    db = FakeDB(profile=None)
    dm = DecisionMaker(db, solver_backend=None, rl_agent=None, redis_cache=_cache_with(client))

    profile = asyncio.run(dm._get_cached_profile("Villain", allow_fetch=True))

    assert profile == {"player_type": "Nit", "derived_profile": {"style": "Nit"}}
    assert db.fetches == 0


def test_profile_miss_writes_through_and_second_read_skips_db(monkeypatch):
    client = FakeRedisClient()
    profile_data = {"player_type": "LAG", "hands_played": 40}
    db = FakeDB(profile=profile_data)
    dm = DecisionMaker(db, solver_backend=None, rl_agent=None, redis_cache=_cache_with(client))

    first = asyncio.run(dm._get_cached_profile("Villain", allow_fetch=True))
    assert first == profile_data
    assert db.fetches == 1
    assert "pkm:profile:Villain" in client.store

    # Nouveau DecisionMaker (caches locaux vides) partageant le même Redis.
    dm2 = DecisionMaker(FakeDB(profile=None), solver_backend=None, rl_agent=None, redis_cache=_cache_with(client))
    second = asyncio.run(dm2._get_cached_profile("Villain", allow_fetch=True))

    assert second == profile_data
    assert second["hands_played"] == 40


def test_broken_redis_falls_back_to_db(monkeypatch):
    db = FakeDB(profile={"player_type": "Balanced"})
    dm = DecisionMaker(db, solver_backend=None, rl_agent=None, redis_cache=_cache_with(BrokenRedisClient()))

    profile = asyncio.run(dm._get_cached_profile("Villain", allow_fetch=True))

    assert profile == {"player_type": "Balanced"}
    assert db.fetches == 1
