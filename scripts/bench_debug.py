#!/usr/bin/env python3
"""Bench debug mode — boot OFF/ON + throttle + CFR sample (optionnel)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# 1) Probe cost — OFF (env absent) vs ON (POKER_DEBUG=1)
# ---------------------------------------------------------------------------

def bench_probe() -> None:
    from src.runtime.debug import probe_debug_enabled

    # OFF
    env_saved = os.getenv("POKER_DEBUG")
    if env_saved is not None:
        del os.environ["POKER_DEBUG"]
    t0 = time.perf_counter()
    for _ in range(1000):
        probe_debug_enabled()
    dt_off = (time.perf_counter() - t0) / 1000 * 1e6  # µs par call

    # ON
    os.environ["POKER_DEBUG"] = "1"
    t0 = time.perf_counter()
    for _ in range(1000):
        probe_debug_enabled()
    dt_on = (time.perf_counter() - t0) / 1000 * 1e6

    # Restore
    if env_saved is None:
        os.environ.pop("POKER_DEBUG", None)
    else:
        os.environ["POKER_DEBUG"] = env_saved

    print(f"probe OFF: {dt_off:.1f} us/call | ON: {dt_on:.1f} us/call")
    assert dt_off < 2000, f"probe OFF trop lent: {dt_off:.1f} us"
    assert dt_on < 50, f"probe ON trop lent: {dt_on:.1f} us"


# ---------------------------------------------------------------------------
# 2) setup_debug_logging idempotence — 2 appels même settings = no-op
# ---------------------------------------------------------------------------

def bench_setup_idempotence(tmp_path: Path | None = None) -> None:
    from src.runtime.debug import setup_debug_logging, _reset_debug_state

    root = tmp_path or (ROOT / ".bench_tmp")
    root.mkdir(parents=True, exist_ok=True)
    _reset_debug_state()
    cfg = {"debug": {"enabled": True, "log_file": str(root / "bench_debug.log")}}
    t0 = time.perf_counter()
    setup_debug_logging(cfg)
    dt_first = (time.perf_counter() - t0) * 1e3
    t0 = time.perf_counter()
    setup_debug_logging(cfg)
    dt_second = (time.perf_counter() - t0) * 1e3
    _reset_debug_state()
    print(f"setup first: {dt_first:.1f} ms | idempotent second: {dt_second:.1f} ms")
    assert dt_second < 5.0, f"idempotence second trop lent: {dt_second:.1f} ms"
    assert dt_second < dt_first * 0.8, "idempotence non effective"


# ---------------------------------------------------------------------------
# 3) Throttle — per-frame guard
# ---------------------------------------------------------------------------

def bench_throttle() -> None:
    from src.runtime.debug import _should_throttle, _throttle_state

    _throttle_state.clear()
    t0 = time.perf_counter()
    emitted = sum(1 for _ in range(10000) if _should_throttle("bench:key", 1.0))
    dt = (time.perf_counter() - t0) * 1e6
    print(f"throttle 10k calls: {dt:.0f} µs total | emitted={emitted} (attendu 1)")
    assert emitted == 1
    assert dt < 5000, f"throttle trop lent: {dt:.0f} µs pour 10k calls"


if __name__ == "__main__":
    bench_probe()
    bench_throttle()
    bench_setup_idempotence()
    print("bench_debug: OK")
