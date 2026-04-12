"""Equity backend selection and response normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from poker.decisionmaker.v2_contracts import CacheTier, EquityBackend


@dataclass(frozen=True)
class EquityPlan:
    backend: EquityBackend
    mode: str
    exact: bool
    reason: str


def _split_range_tokens(range_string: str) -> list[str]:
    return [token.strip() for token in str(range_string or "").split(",") if token.strip()]


def _is_closed_spot(board: list[str], villain_ranges: list[str]) -> bool:
    if len(board) >= 5:
        return True
    token_count = sum(len(_split_range_tokens(range_string)) for range_string in villain_ranges)
    return len(board) >= 4 and token_count <= 24


def _exact_is_affordable(
    board: list[str],
    villain_ranges: list[str],
    time_budget_ms: int | None,
) -> bool:
    budget = 0 if time_budget_ms in (None, 0) else int(time_budget_ms)
    token_count = sum(len(_split_range_tokens(range_string)) for range_string in villain_ranges)
    if _is_closed_spot(board, villain_ranges):
        return True
    if budget >= 2200 and len(board) >= 4 and token_count <= 48:
        return True
    return False


def build_equity_plan(
    board: list[str],
    villain_ranges: list[str],
    *,
    preferred_mode: str = "auto",
    time_budget_ms: int | None = None,
    allow_oracle: bool = False,
) -> EquityPlan:
    normalized_mode = str(preferred_mode or "auto").strip().lower()
    if normalized_mode == "oracle":
        return EquityPlan(
            backend=EquityBackend.ORACLE_BACKEND,
            mode="oracle",
            exact=True,
            reason="forced_oracle_mode",
        )
    if normalized_mode == "exact":
        return EquityPlan(
            backend=EquityBackend.RUST_EXACT,
            mode="exact",
            exact=True,
            reason="forced_exact_mode",
        )
    if normalized_mode == "monte_carlo":
        return EquityPlan(
            backend=EquityBackend.RUST_MONTE_CARLO,
            mode="monte_carlo",
            exact=False,
            reason="forced_monte_carlo_mode",
        )

    if allow_oracle and len(board) >= 5:
        return EquityPlan(
            backend=EquityBackend.ORACLE_BACKEND,
            mode="oracle",
            exact=True,
            reason="river_showdown_oracle",
        )

    if _exact_is_affordable(board, villain_ranges, time_budget_ms):
        return EquityPlan(
            backend=EquityBackend.RUST_EXACT,
            mode="exact",
            exact=True,
            reason="closed_or_affordable_exact_spot",
        )

    return EquityPlan(
        backend=EquityBackend.RUST_MONTE_CARLO,
        mode="monte_carlo",
        exact=False,
        reason="range_breadth_or_budget_requires_sampling",
    )


def select_equity_backend(
    board: list[str],
    villain_ranges: list[str],
    *,
    preferred_mode: str = "auto",
    time_budget_ms: int | None = None,
    allow_oracle: bool = False,
) -> tuple[EquityBackend, str]:
    plan = build_equity_plan(
        board,
        villain_ranges,
        preferred_mode=preferred_mode,
        time_budget_ms=time_budget_ms,
        allow_oracle=allow_oracle,
    )
    return plan.backend, plan.mode


def normalize_equity_response(
    response: dict[str, Any],
    *,
    backend: EquityBackend,
    mode: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized = dict(response)
    normalized.setdefault("backend", backend.value)
    normalized.setdefault("mode", mode or backend.value)
    normalized.setdefault(
        "cache_tier",
        CacheTier.MEMORY.value if normalized.get("cache_hit") else CacheTier.NONE.value,
    )
    normalized.setdefault("selection_reason", reason or "unspecified")
    return normalized
