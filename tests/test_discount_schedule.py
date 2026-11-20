"""Traçabilité du schedule de discount CFR (spec `012`, T009/T010).

Le schedule est sélectionnable par la requête (contrat Rust) et tracé dans
`metadata["discount_schedule"]`. Côté Python, deux défauts historiques du projet
sont ici couverts :

1. la clé doit traverser l'allowlist native (`_NATIVE_SOLVE_KEYS`) — sans quoi
   elle serait silencieusement supprimée avant l'appel natif (même défaut que le
   `FormatProfile` orphelin de la spec `005`) ;
2. le schedule doit faire partie de l'identité du spot dans le cache — sans quoi
   un hit de cache sous DCFR servirait une requête HS-DCFR.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.solver.provider import _NATIVE_SOLVE_KEYS, SolverProvider
from src.solver.spot_key import spot_cache_key

BASE_SPOT = {
    "hero_hand": "AhKd",
    "villain_range": "QQ+,AK",
    "board": ["2c", "7d", "Jh"],
    "pot": 10.0,
    "effective_stack": 80.0,
    "legal_actions": ["CHECK", "BET"],
    "spot_id": "s1",
    "hero_position": "BTN",
    "action_history": [],
}


def test_discount_schedule_is_allowed_through_to_the_native_solver():
    """T009 — la clé traverse l'allowlist native (sinon elle est supprimée)."""
    assert "discount_schedule" in _NATIVE_SOLVE_KEYS


def test_native_backend_receives_the_discount_schedule():
    """T009 (suite) — la clé atteint réellement l'appel natif, valeur comprise."""
    calls: list[dict] = []

    class RecordingBackend:
        backend_name = "recording"

        def solve_spot_v2(self, **kwargs):
            calls.append(kwargs)
            return {"chosen_action": "CHECK", "backend": "native_solver"}

    provider = SolverProvider(native_backend=RecordingBackend())
    provider.solve_spot_v2(**BASE_SPOT, discount_schedule="hs_dcfr_30")

    assert calls, "le backend natif doit avoir été appelé"
    assert calls[0].get("discount_schedule") == "hs_dcfr_30"


def test_absent_schedule_is_not_injected_into_the_native_call():
    """FR-001 — sans sélection, rien n'est transmis : le défaut reste inchangé."""
    calls: list[dict] = []

    class RecordingBackend:
        backend_name = "recording"

        def solve_spot_v2(self, **kwargs):
            calls.append(kwargs)
            return {"chosen_action": "CHECK", "backend": "native_solver"}

    provider = SolverProvider(native_backend=RecordingBackend())
    provider.solve_spot_v2(**BASE_SPOT)

    assert calls
    assert "discount_schedule" not in calls[0]


def test_spot_cache_key_separates_schedules_and_stays_stable_when_absent():
    """Le schedule fait partie de l'identité du spot, sans casser le défaut."""
    legacy = spot_cache_key(**BASE_SPOT)
    same = spot_cache_key(**BASE_SPOT)
    hs30 = spot_cache_key(**BASE_SPOT, discount_schedule="hs_dcfr_30")
    hs15 = spot_cache_key(**BASE_SPOT, discount_schedule="hs_dcfr_15")
    blank = spot_cache_key(**BASE_SPOT, discount_schedule="")

    # Le défaut reste byte-identique (aucune régression du cache existant).
    assert legacy == same
    assert blank == legacy
    # Chaque schedule a sa propre identité.
    assert hs30 != legacy
    assert hs15 != legacy
    assert hs30 != hs15
    # La casse ne crée pas de doublon d'identité.
    assert spot_cache_key(**BASE_SPOT, discount_schedule="HS_DCFR_30") == hs30


def test_config_json_carries_no_inert_schedule_key():
    """SC-004/FR-014 — aucune clé de schedule sans effet dans `config.json`.

    La clé `solver.hs_pcf_30_enabled` n'était lue par aucun code : elle suggérait
    un réglage inexistant. Le schedule se sélectionne par requête ou par
    `POKER_DISCOUNT_SCHEDULE`, jamais par une clé de config inerte.
    """
    import json

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    solver = config.get("solver") or {}
    for key in solver:
        assert "hs_pcf" not in key, f"clé de schedule inerte restante : solver.{key}"
        assert "discount_schedule" not in key, (
            f"le schedule doit rester une sélection par requête, pas une clé "
            f"de config sans câblage : solver.{key}"
        )
