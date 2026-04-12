"""Canonical tree preset catalog inspired by desktop-postflop and wasm-postflop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from poker.decisionmaker.v2_contracts import (
    CachePolicy,
    OcrConfidenceReport,
    RangeModelVersion,
    SolveRequestV2,
    SpotSnapshot,
)


@dataclass(frozen=True)
class TreePresetDefinition:
    preset_id: str
    title: str
    family: str
    description: str
    street_focus: str
    hero_position: str
    player_count: int
    starting_pot: float
    effective_stack: float
    board: tuple[str, ...]
    hero_range: str
    villain_ranges: tuple[str, ...]
    action_history: tuple[str, ...]
    legal_actions: tuple[str, ...]
    default_time_budget_ms: int
    compression: str = "balanced"
    desktop_profile: str = "desktop-postflop"
    wasm_profile: str = "wasm-postflop"
    tags: tuple[str, ...] = ()

    def build_spot_snapshot(self) -> SpotSnapshot:
        return SpotSnapshot(
            spot_id=f"preset:{self.preset_id}",
            source="preset_catalog",
            game_stage=self.street_focus.title(),
            hero_cards=("As", "Kd"),
            board=self.board,
            hero_position=self.hero_position,
            positions={"hero": self.hero_position, "villain": "opp"},
            pot=self.starting_pot,
            stack=self.effective_stack,
            legal_actions=self.legal_actions,
            action_history=self.action_history,
            hero_range=self.hero_range,
            villain_ranges=self.villain_ranges,
            state_confidence=0.98,
            ocr_confidence=OcrConfidenceReport(
                overall=0.98,
                hero_cards=1.0,
                board=1.0,
                pot=0.96,
                stack=0.96,
                actions=0.98,
                notes=("preset_catalog", self.desktop_profile, self.wasm_profile),
            ),
            range_model_version=RangeModelVersion.CALIBRATED_V3,
            metadata={
                "compression": self.compression,
                "desktop_profile": self.desktop_profile,
                "wasm_profile": self.wasm_profile,
                "family": self.family,
                "tags": list(self.tags),
            },
        )

    def build_solve_request(
        self,
        *,
        cache_policy: CachePolicy = CachePolicy.PERSISTENT,
        time_budget_ms: int | None = None,
    ) -> SolveRequestV2:
        spot = self.build_spot_snapshot()
        return SolveRequestV2(
            spot_id=spot.spot_id,
            hero_range=self.hero_range,
            villain_ranges=self.villain_ranges,
            board=self.board,
            starting_pot=self.starting_pot,
            effective_stack=self.effective_stack,
            hero_position=self.hero_position,
            action_history=self.action_history,
            tree_preset_id=self.preset_id,
            rake=0.0,
            num_players=self.player_count,
            legal_actions=tuple(),
            cache_policy=cache_policy,
            hero_confidence=1.0,
            state_confidence=spot.state_confidence,
            range_model_version=RangeModelVersion.CALIBRATED_V3,
            use_cache=True,
            time_budget_ms=time_budget_ms or self.default_time_budget_ms,
            metadata={
                "compression": self.compression,
                "desktop_profile": self.desktop_profile,
                "wasm_profile": self.wasm_profile,
                "street_focus": self.street_focus,
                "tags": list(self.tags),
            },
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "family": self.family,
            "description": self.description,
            "street_focus": self.street_focus,
            "hero_position": self.hero_position,
            "player_count": self.player_count,
            "starting_pot": self.starting_pot,
            "effective_stack": self.effective_stack,
            "default_time_budget_ms": self.default_time_budget_ms,
            "compression": self.compression,
            "desktop_profile": self.desktop_profile,
            "wasm_profile": self.wasm_profile,
            "tags": list(self.tags),
        }


_PRESET_CATALOG: tuple[TreePresetDefinition, ...] = (
    TreePresetDefinition(
        preset_id="srp_hu_100bb",
        title="SRP HU 100bb",
        family="srp",
        description="Single-raised pot baseline for fast flop solves and parity checks.",
        street_focus="flop",
        hero_position="ip",
        player_count=2,
        starting_pot=6.5,
        effective_stack=93.5,
        board=("Ah", "Kd", "7c"),
        hero_range="QQ+,AKs,AKo,AQs,AJs,KQs",
        villain_ranges=("22+,A2s+,K8s+,Q9s+,JTs,T9s,A9o+,KTo+,QTo+",),
        action_history=("preflop:raise", "flop:check"),
        legal_actions=("check", "bet_33", "bet_50", "bet_100"),
        default_time_budget_ms=1400,
        compression="balanced",
        tags=("baseline", "heads_up", "desktop-compatible"),
    ),
    TreePresetDefinition(
        preset_id="srp_hu_texture_wet",
        title="SRP HU Wet Board",
        family="srp",
        description="Wet flop preset aligned with common texture exploration in desktop tools.",
        street_focus="flop",
        hero_position="oop",
        player_count=2,
        starting_pot=6.5,
        effective_stack=93.5,
        board=("Jh", "Th", "8c"),
        hero_range="TT+,AJs+,KQs,AKo",
        villain_ranges=("22+,A2s+,K9s+,QTs+,JTs,T9s,98s,A9o+,KTo+,QJo",),
        action_history=("preflop:call", "flop:check"),
        legal_actions=("check", "bet_50", "bet_75", "bet_125"),
        default_time_budget_ms=1700,
        compression="texture-aware",
        tags=("wet_board", "heads_up", "wasm-compatible"),
    ),
    TreePresetDefinition(
        preset_id="3bp_hu_100bb",
        title="3BP HU 100bb",
        family="3bet",
        description="Three-bet pot preset for condensed ranges and higher-pressure postflop trees.",
        street_focus="flop",
        hero_position="oop",
        player_count=2,
        starting_pot=22.0,
        effective_stack=78.0,
        board=("Qs", "9h", "4d"),
        hero_range="QQ+,AKs,AKo,AQs",
        villain_ranges=("88-JJ,AJs+,KQs,AQo+",),
        action_history=("preflop:3bet", "flop:check"),
        legal_actions=("check", "bet_25", "bet_50", "jam"),
        default_time_budget_ms=1800,
        compression="pressure",
        tags=("3bet", "pressure", "desktop-compatible"),
    ),
    TreePresetDefinition(
        preset_id="4bp_hu_100bb",
        title="4BP HU 100bb",
        family="4bet",
        description="Four-bet pot preset for shallow SPR and tight polarized ranges.",
        street_focus="flop",
        hero_position="ip",
        player_count=2,
        starting_pot=40.0,
        effective_stack=60.0,
        board=("Jc", "7s", "2d"),
        hero_range="QQ+,AKs,AKo",
        villain_ranges=("TT+,AQs+,AKo",),
        action_history=("preflop:4bet", "flop:check"),
        legal_actions=("check", "bet_25", "bet_50", "jam"),
        default_time_budget_ms=1900,
        compression="pressure",
        tags=("4bet", "shallow_spr", "wasm-compatible"),
    ),
    TreePresetDefinition(
        preset_id="turn_probe_hu",
        title="Turn Probe HU",
        family="turn",
        description="Turn probe preset after flop checks, used for delayed-aggression review loops.",
        street_focus="turn",
        hero_position="oop",
        player_count=2,
        starting_pot=18.0,
        effective_stack=76.0,
        board=("Kd", "8s", "3c", "2h"),
        hero_range="AJs+,KQs,99+,AQo+",
        villain_ranges=("66-QQ,A9s+,KTs+,QTs+,JTs,T9s,AJo+,KQo",),
        action_history=("preflop:raise", "flop:check", "turn:probe"),
        legal_actions=("check", "bet_50", "bet_75", "jam"),
        default_time_budget_ms=1600,
        compression="turn-probe",
        tags=("turn", "probe", "desktop-compatible"),
    ),
    TreePresetDefinition(
        preset_id="turn_delayed_cbet_hu",
        title="Turn Delayed C-Bet HU",
        family="turn",
        description="Delayed c-bet turn tree modeled after desktop inspection workflows.",
        street_focus="turn",
        hero_position="ip",
        player_count=2,
        starting_pot=15.0,
        effective_stack=82.0,
        board=("Qc", "7d", "2s", "4h"),
        hero_range="QQ+,AQs+,AJo+,KQs",
        villain_ranges=("22-JJ,A2s+,K9s+,QTs+,JTs,T9s,A9o+,KTo+",),
        action_history=("preflop:raise", "flop:check_back", "turn:delayed_cbet"),
        legal_actions=("check", "bet_33", "bet_66", "bet_100"),
        default_time_budget_ms=1650,
        compression="turn-delay",
        tags=("turn", "delay", "wasm-compatible"),
    ),
    TreePresetDefinition(
        preset_id="river_jam_low_spr",
        title="River Jam Low SPR",
        family="river",
        description="Low-SPR river preset for jam-or-check nodes.",
        street_focus="river",
        hero_position="ip",
        player_count=2,
        starting_pot=42.0,
        effective_stack=28.0,
        board=("Jc", "7d", "4s", "2c", "2s"),
        hero_range="TT+,AQs+,AKo",
        villain_ranges=("88+,ATs+,KQs,AQo+",),
        action_history=("preflop:raise", "flop:bet", "turn:check", "river:decision"),
        legal_actions=("check", "bet_75", "jam"),
        default_time_budget_ms=1100,
        compression="endgame",
        tags=("river", "jam", "low_spr"),
    ),
    TreePresetDefinition(
        preset_id="river_overbet_polar_hu",
        title="River Overbet Polar HU",
        family="river",
        description="Polarized river overbet tree for capped-versus-uncapped endgames.",
        street_focus="river",
        hero_position="oop",
        player_count=2,
        starting_pot=38.0,
        effective_stack=52.0,
        board=("As", "Ts", "6d", "6c", "2h"),
        hero_range="AA,TT,ATs,AQo,KQs,QJs,76s",
        villain_ranges=("77-QQ,A9s+,KTs+,QTs+,JTs,AJo+,KQo",),
        action_history=("preflop:3bet", "flop:bet", "turn:check"),
        legal_actions=("check", "bet_75", "bet_150", "jam"),
        default_time_budget_ms=1450,
        compression="polar-endgame",
        tags=("river", "overbet", "polar"),
    ),
)


def list_tree_presets() -> list[TreePresetDefinition]:
    return list(_PRESET_CATALOG)


def list_tree_preset_ids() -> list[str]:
    return [preset.preset_id for preset in _PRESET_CATALOG]


def get_tree_preset(preset_id: str) -> TreePresetDefinition:
    for preset in _PRESET_CATALOG:
        if preset.preset_id == preset_id:
            return preset
    return _PRESET_CATALOG[0]


def preset_catalog_payload() -> list[dict[str, Any]]:
    return [preset.to_summary() for preset in _PRESET_CATALOG]


def build_prewarm_requests(
    preset_ids: list[str] | tuple[str, ...] | None = None,
    *,
    cache_policy: CachePolicy = CachePolicy.PERSISTENT,
    time_budget_ms: int | None = None,
) -> list[SolveRequestV2]:
    selected_ids = set(preset_ids or list_tree_preset_ids())
    requests: list[SolveRequestV2] = []
    for preset in _PRESET_CATALOG:
        if preset.preset_id in selected_ids:
            requests.append(
                preset.build_solve_request(
                    cache_policy=cache_policy,
                    time_budget_ms=time_budget_ms,
                )
            )
    return requests


def choose_tree_preset_id(
    *,
    game_stage: str,
    pot_bb: float,
    eff_stack_bb: float,
    hero_is_oop: bool,
    action_history: tuple[str, ...] | list[str] = (),
) -> str:
    normalized_stage = str(game_stage or "").lower()
    history = " ".join(str(item).lower() for item in action_history)

    if normalized_stage == "river":
        if eff_stack_bb <= max(24.0, pot_bb * 0.8):
            return "river_jam_low_spr"
        if "3bet" in history or "4bet" in history or not hero_is_oop:
            return "river_overbet_polar_hu"
        return "river_jam_low_spr"

    if normalized_stage == "turn":
        if "check_back" in history or "delayed" in history:
            return "turn_delayed_cbet_hu"
        return "turn_probe_hu"

    if pot_bb >= 32.0 or eff_stack_bb <= 65.0:
        return "4bp_hu_100bb"
    if pot_bb >= 16.0:
        return "3bp_hu_100bb"
    if hero_is_oop:
        return "srp_hu_texture_wet"
    return "srp_hu_100bb"
