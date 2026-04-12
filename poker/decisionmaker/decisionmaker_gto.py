"""
decisionmaker_gto.py — Remplacement drop-in de decisionmaker.py pour les streets postflop
Conserve l'original de dickreuter pour le preflop.

Architecture :
    ┌─────────────────────────────────────────────────────────┐
    │  dickreuter scraper (OpenCV)                            │
    │    t.gameStage, t.mycards, t.cardsOnTable,              │
    │    t.totalPotValue, t.myFunds, t.minCall, t.bigBlind    │
    └──────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────▼────────────────┐
          │  RangeTrackerManager        │
          │  (inférence range villain)  │
          └────────────┬────────────────┘
                       │
          ┌────────────▼────────────────┐
          │  Preflop ?                  │
          │  → DecisionMaker original   │ (algo génétique + Monte Carlo inchangé)
          │  Postflop ?                 │
          │  → POST /solve (Rust API)   │ (Discounted CFR via postflop-solver)
          └────────────┬────────────────┘
                       │
          ┌────────────▼────────────────┐
          │  Action finale              │
          │  fold / check / call / bet  │
          └─────────────────────────────┘

Usage (dans main.py de dickreuter) :
    # Remplacer :
    #   from poker.decisionmaker.decisionmaker import DecisionMaker
    # Par :
    #   from poker.decisionmaker.decisionmaker_gto import DecisionMakerGTO as DecisionMaker
"""

import importlib
import time
import logging
from enum import Enum
from typing import Optional

import requests

from poker.decisionmaker.decision_service import CanonicalDecisionService
from poker.decisionmaker.gto_runtime import ensure_local_gto_server
from poker.decisionmaker.range_tracker import RangeTrackerManager
from poker.decisionmaker.tree_presets import choose_tree_preset_id
from poker.decisionmaker.v2_contracts import (
    ActionEstimate,
    CachePolicy,
    CacheTier,
    DecisionSnapshot,
    SolveRequestV2,
    SolveResponseV2,
    SpotSnapshot,
)

# Import du DecisionMaker original pour le preflop (on ne touche pas à ce qui marche)
try:
    # dickreuter expose la classe Decision (pas DecisionMaker)
    from poker.decisionmaker.decisionmaker import Decision as OriginalDecisionMaker, DecisionTypes
except ImportError:
    # Fallback pour tests isolés
    OriginalDecisionMaker = None
    class DecisionTypes(Enum):
        fold  = "Fold"
        check = "Check"
        call  = "Call"
        bet1  = "Bet"
        bet2  = "BetPlus"
        bet3  = "Bet half pot"
        bet4  = "Bet pot"

logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────────

GTO_SERVER_URL = "http://127.0.0.1:8765"
GTO_TIMEOUT_SEC = 10       # Timeout requête HTTP (le solve est rapide ~50-200ms)
GTO_MAX_ITER = 200         # Itérations CFR (200 = rapide, 1000 = précis)
GTO_EXPLOITABILITY = 0.5  # Seuil d'arrêt en BB (0.5 BB = suffisant en pratique)

NATIVE_GTO_MODULE_CANDIDATES = (
    "poker.gto_binding",
    "poker.postflop_solver",
    "poker.native_gto",
    "gto_binding",
    "postflop_solver",
    "postflop_solver_py",
)

NATIVE_GTO_FUNCTION_CANDIDATES = (
    "solve_spot_v2",
    "solve_spot",
    "solve_postflop",
    "solve_gto",
    "solve",
)


# ─── Conversion cartes ─────────────────────────────────────────────────────────

# Table de correspondance dickreuter → format postflop-solver
# dickreuter stocke les cartes comme "As", "Kh", "Tc", "2d" — déjà compatible
def normalize_card(card: str) -> str:
    """Normalise une carte du format dickreuter vers le format postflop-solver."""
    if not card or len(card) < 2:
        return ""
    rank = card[0].upper()
    suit = card[1].lower()
    # Gérer "10" → "T"
    if rank == "1" and len(card) == 3:
        rank = "T"
        suit = card[2].lower()
    return f"{rank}{suit}"


def parse_board(t) -> list[str]:
    """Extrait et normalise les cartes communes depuis l'objet table dickreuter."""
    cards_on_table = getattr(t, 'cardsOnTable', []) or []
    board = [normalize_card(c) for c in cards_on_table if c]
    return [c for c in board if c]  # Filtrer les vides


# ─── Conversion action solver → DecisionTypes ──────────────────────────────────

def solver_action_to_decision(action_name: str, t) -> "DecisionTypes":
    """
    Traduit l'action retournée par le solver GTO vers les DecisionTypes de dickreuter.
    Prend en compte les boutons disponibles (t.checkButton, t.minCall).
    """
    action = action_name.lower()
    has_check = getattr(t, 'checkButton', False)
    min_call   = getattr(t, 'minCall', 0) or 0

    if action == "fold":
        return DecisionTypes.fold

    if action == "check":
        if has_check:
            return DecisionTypes.check
        else:
            # Pas de check possible → call ou fold selon pot odds
            return DecisionTypes.call if min_call > 0 else DecisionTypes.check

    if action == "call":
        return DecisionTypes.call

    if "raise" in action or "allin" in action:
        return DecisionTypes.bet2   # BetPlus = relance

    if "bet" in action:
        # Choisir la taille selon le ratio bet/pot
        try:
            size_str = action.split("_")[-1].replace("%", "")
            size_value = float(size_str)
        except (ValueError, IndexError):
            size_value = 50.0

        big_blind = getattr(t, 'bigBlind', 1.0) or 1.0
        pot_bb = (getattr(t, 'totalPotValue', big_blind * 2) or big_blind * 2) / big_blind
        if pot_bb > 0 and size_value > 1.0:
            size_ratio = size_value / pot_bb
        else:
            size_ratio = size_value / 100.0 if size_value > 1.0 else size_value

        if size_ratio <= 0.35:
            return DecisionTypes.bet1    # Bet (small)
        elif size_ratio <= 0.65:
            return DecisionTypes.bet3    # Bet half pot
        else:
            return DecisionTypes.bet4    # Bet pot

    # Par défaut
    return DecisionTypes.check if has_check else DecisionTypes.call


# ─── Calcul du stack effectif ──────────────────────────────────────────────────

def compute_effective_stack(t) -> float:
    """
    Calcule le stack effectif (min des stacks actifs) en BB.
    Utilise les données de t.other_players et t.myFunds.
    """
    big_blind = getattr(t, 'bigBlind', 1.0) or 1.0
    my_funds  = getattr(t, 'myFunds', 100.0) or 100.0

    villain_stacks = []
    for player in getattr(t, 'other_players', []):
        funds = getattr(player, 'funds', 0) or 0
        status = getattr(player, 'status', 'folded') or 'folded'
        if status != 'folded' and funds > 0:
            villain_stacks.append(funds)

    if not villain_stacks:
        return my_funds / big_blind

    effective = min(my_funds, min(villain_stacks))
    return effective / big_blind


# ─── Classe principale ─────────────────────────────────────────────────────────

class DecisionGTO:
    """
    Drop-in replacement de la classe Decision de dickreuter/Poker.
    Interface identique — main.py de dickreuter appelle :
        d = Decision(table, history, strategy, game_logger)
        d.make_decision(table, history, strategy, game_logger)
        mouse_target = d.decision

    - Preflop : délègue à l'original (génétique + Monte Carlo)
    - Postflop : essaie d'abord le binding natif Python, puis le serveur GTO via HTTP
    """

    # Tracker partagé entre toutes les instances (persist entre les mains)
    _range_tracker = RangeTrackerManager()
    _decision_service = CanonicalDecisionService()

    def __init__(self, table, history, strategy, game_logger):
        self.t = table
        self.h = history
        self.p = strategy
        self.l = game_logger
        # Attributs lus par main.py après la décision
        self.decision: DecisionTypes = DecisionTypes.check
        self.finalCallLimit: float = 0.0
        self.finalBetLimit: float = 0.0
        self.maxCallEV: float = 0.0
        self.outs: int = 0
        self.pot_multiple: float = 0.0
        self.spot_snapshot_v2 = None
        self.solve_request_v2 = None
        self.solve_response_v2 = None
        self.decision_snapshot_v2 = None
        self.decision_gate_v2 = None
        self._last_solver_source = "legacy"

    def make_decision(self, table, history, strategy, game_logger) -> None:
        """Appelé par main.py après __init__. Lance la logique de décision."""
        self.t = table
        self.h = history
        self.p = strategy
        self.l = game_logger
        self._make_decision()

    def _make_decision(self) -> None:
        game_stage = getattr(self.t, 'gameStage', 'PreFlop')
        self._refresh_spot_snapshot_v2()

        # ── Preflop : garder l'original de dickreuter ─────────────────────────
        if game_stage == 'PreFlop':
            self._decide_preflop()
            return

        # ── Postflop : appel au solver GTO ────────────────────────────────────
        board = parse_board(self.t)
        if len(board) < 3:
            logger.warning("Board incomplet (%d cartes), blocking action", len(board))
            self._set_no_action("incomplete_board", warnings=("incomplete_board",))
            return

        if not getattr(self.t, 'isHeadsUp', False):
            logger.info("Multiway postflop spot detected, skipping solver and using fallback logic")
            self._decide_postflop_fallback()
            return

        # Mettre à jour les ranges
        try:
            self._range_tracker.update_from_table(self.t)
            villain_range = self._range_tracker.get_primary_villain_range()
            villain_state = self._range_tracker.get_primary_villain_state()
        except Exception as exc:
            logger.warning("Range tracker failed, falling back to original logic: %s", exc)
            self._decide_postflop_fallback()
            return

        # Construire la range hero (main exacte avec coeff 1.0)
        hero_range = self._build_hero_range()
        if not hero_range:
            logger.warning("Range hero vide, fallback")
            self._decide_postflop_fallback()
            return

        # Déterminer si hero est OOP
        hero_is_oop = self._hero_is_oop()

        # Taille du pot et stack en BB
        big_blind     = getattr(self.t, 'bigBlind', 1.0) or 1.0
        pot_bb        = (getattr(self.t, 'totalPotValue', big_blind * 2) or big_blind * 2) / big_blind
        eff_stack_bb  = compute_effective_stack(self.t)
        self._update_spot_snapshot_ranges(hero_range, villain_range, game_stage, villain_state)

        if self.spot_snapshot_v2 is not None:
            self.decision_gate_v2 = self._decision_service.evaluate_gate(self.spot_snapshot_v2)
            if not self.decision_gate_v2.allowed:
                logger.warning("Decision gate blocked live action: %s", self.decision_gate_v2.reason)
                self._set_no_action(
                    self.decision_gate_v2.reason,
                    warnings=self.decision_gate_v2.warnings or ("decision_gate_blocked",),
                )
                return

        self.solve_request_v2 = self._build_postflop_solve_request_v2(
            hero_range=hero_range,
            villain_range=villain_range,
            board=board,
            pot_bb=pot_bb,
            eff_stack_bb=eff_stack_bb,
            hero_is_oop=hero_is_oop,
            game_stage=game_stage,
        )

        logger.debug("Requête GTO: board=%s pot=%.1fBB stack=%.1fBB hero_oop=%s",
                     board, pot_bb, eff_stack_bb, hero_is_oop)

        solve_result = self._decision_service.solve_request(
            self.solve_request_v2,
            self._call_native_gto_solver_v2_result,
            self._call_gto_server_v2_result,
        )
        action = self._extract_solver_action(solve_result)
        if action:
            self._apply_runtime_decision(solver_action_to_decision(action, self.t))
            self.finalCallLimit = getattr(self.t, 'minCall', 0.0) or 0.0
            self.finalBetLimit = getattr(self.t, 'minBet', 0.0) or 0.0
            self.solve_response_v2 = self._build_solve_response_v2(action, solve_result)
            self._record_decision_snapshot(self._last_solver_source)
            logger.info("[GTO] %s → %s (street=%s)", action, self.decision, game_stage)
        else:
            self._decide_postflop_fallback()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _current_action_history(self) -> tuple[str, ...]:
        if self.spot_snapshot_v2 is None:
            return tuple()
        history = getattr(self.spot_snapshot_v2, "action_history", ()) or ()
        return tuple(str(item) for item in history if item not in (None, ""))

    def _build_postflop_solve_request_v2(
        self,
        hero_range: str,
        villain_range: str,
        board: list[str],
        pot_bb: float,
        eff_stack_bb: float,
        hero_is_oop: bool,
        game_stage: str,
    ) -> SolveRequestV2:
        selected_preset_id = choose_tree_preset_id(
            game_stage=game_stage,
            pot_bb=pot_bb,
            eff_stack_bb=eff_stack_bb,
            hero_is_oop=hero_is_oop,
            action_history=self._current_action_history(),
        )
        time_budget_ms = max(int(GTO_TIMEOUT_SEC * 1000), 1200 if game_stage == "River" else 1500)
        if self.spot_snapshot_v2 is not None:
            self.spot_snapshot_v2.pot = round(pot_bb, 1)
            self.spot_snapshot_v2.stack = round(eff_stack_bb, 1)
            self.spot_snapshot_v2.hero_position = "oop" if hero_is_oop else "ip"
            self.spot_snapshot_v2.board = tuple(board)
            return self._decision_service.build_solve_request(
                self.spot_snapshot_v2,
                hero_range,
                (villain_range,),
                hero_position="oop" if hero_is_oop else "ip",
                tree_preset_id=selected_preset_id,
                rake=0.0,
                num_players=2,
                time_budget_ms=time_budget_ms,
                use_cache=True,
                cache_policy=CachePolicy.PERSISTENT,
                metadata={"game_stage": game_stage, "selected_preset_id": selected_preset_id},
            )

        return SolveRequestV2(
            spot_id="",
            hero_range=hero_range,
            villain_ranges=(villain_range,),
            board=tuple(board),
            starting_pot=round(pot_bb, 1),
            effective_stack=round(eff_stack_bb, 1),
            hero_position="oop" if hero_is_oop else "ip",
            action_history=self._current_action_history(),
            tree_preset_id=selected_preset_id,
            rake=0.0,
            num_players=2,
            legal_actions=(),
            cache_policy=CachePolicy.PERSISTENT,
            hero_confidence=1.0,
            state_confidence=0.0,
            use_cache=True,
            time_budget_ms=time_budget_ms,
            metadata={"game_stage": game_stage, "selected_preset_id": selected_preset_id},
        )

    def _build_legacy_solver_payload(self, solve_request: SolveRequestV2) -> dict:
        hero_is_oop = str(solve_request.hero_position).lower() == "oop"
        hero_range = solve_request.hero_range
        villain_range = solve_request.villain_ranges[0] if solve_request.villain_ranges else ""
        return {
            "oop_range": hero_range if hero_is_oop else villain_range,
            "ip_range": villain_range if hero_is_oop else hero_range,
            "board": list(solve_request.board),
            "starting_pot": solve_request.starting_pot,
            "effective_stack": solve_request.effective_stack,
            "hero_is_oop": hero_is_oop,
            "max_iterations": GTO_MAX_ITER,
            "target_exploitability": GTO_EXPLOITABILITY,
            "action_history": list(solve_request.action_history),
            "tree_preset_id": solve_request.tree_preset_id,
            "num_players": solve_request.num_players,
        }

    def _update_spot_snapshot_ranges(self, hero_range: str, villain_range: str, game_stage: str, villain_state) -> None:
        if self.spot_snapshot_v2 is None:
            return
        self.spot_snapshot_v2.hero_range = hero_range
        self.spot_snapshot_v2.villain_ranges = (villain_range,)
        self.spot_snapshot_v2.game_stage = game_stage
        if villain_state is not None:
            self.spot_snapshot_v2.range_model_version = getattr(
                villain_state,
                "model_version",
                getattr(self.spot_snapshot_v2, "range_model_version", None),
            )
            self.spot_snapshot_v2.metadata["range_tracker_actions"] = list(
                getattr(villain_state, "action_history", [])
            )
        self.spot_snapshot_v2.metadata["calibration_rows"] = self._range_tracker.build_calibration_rows(self.t)

    def _apply_runtime_decision(self, decision) -> None:
        self.decision = getattr(decision, "value", decision)

    def _build_hero_range(self) -> str:
        """
        Construit la range hero depuis sa main exacte (t.mycards).
        Format : "AsKh" pour As et Kh.
        """
        my_cards = getattr(self.t, 'mycards', []) or []
        if len(my_cards) < 2:
            return ""
        c1 = normalize_card(str(my_cards[0]))
        c2 = normalize_card(str(my_cards[1]))
        if not c1 or not c2:
            return ""
        return f"{c1}{c2}"

    def _hero_is_oop(self) -> bool:
        """
        Estime si le hero est OOP (out of position).
        Dans dickreuter, position_utg_plus : 0=UTG, 3=BTN, 4=SB, 5=BB.
        OOP = SB (4) ou BB (5) sur la plupart des boards.
        """
        pos = getattr(self.t, 'position_utg_plus', 0) or 0
        return pos in (4, 5)  # SB, BB = OOP

    def _refresh_spot_snapshot_v2(self) -> None:
        try:
            self.spot_snapshot_v2 = SpotSnapshot.from_legacy(
                self.t,
                self.h,
                self.p,
                source="ocr",
            )
        except Exception as exc:
            logger.debug("Unable to build V2 spot snapshot: %s", exc)
            self.spot_snapshot_v2 = None

    def _record_decision_snapshot(self, source: str, warnings: tuple[str, ...] = ()) -> None:
        try:
            snapshot_source = self._resolve_snapshot_source(source)
            response_metadata = dict(getattr(self.solve_response_v2, "metadata", {}) or {})
            alternatives = tuple(
                action
                if isinstance(action, ActionEstimate)
                else ActionEstimate.from_dict(action)
                for action in getattr(self.solve_response_v2, "actions", ())
            )
            ev_by_action = {action.name: action.ev for action in alternatives}
            action_name = getattr(self.decision, "value", self.decision)
            self.decision_snapshot_v2 = DecisionSnapshot(
                action=str(action_name),
                alternatives=alternatives,
                ev_by_action=ev_by_action,
                exploitability=float(getattr(self.solve_response_v2, "exploitability", 0.0) or 0.0),
                source=snapshot_source,
                warnings=warnings or tuple(getattr(self.solve_response_v2, "warnings", ()) or ()),
                latency_ms=int(getattr(self.solve_response_v2, "elapsed_ms", 0) or 0),
                confidence=float(getattr(self.solve_response_v2, "decision_confidence", 1.0 if snapshot_source in {"native", "http"} else 0.45) or 0.0),
                gate_result=getattr(self, "decision_gate_v2", None),
                metadata={
                    "solver_source": snapshot_source,
                    "solver_transport": response_metadata.get(
                        "solver_transport",
                        self._last_solver_source if self._last_solver_source in {"native", "http"} else "",
                    ),
                    "game_stage": getattr(getattr(self, "t", None), "gameStage", ""),
                    "backend": getattr(self.solve_response_v2, "backend", source),
                    "cache_tier": getattr(getattr(self.solve_response_v2, "cache_tier", None), "value", getattr(self.solve_response_v2, "cache_tier", "")),
                    "fallback_reason": getattr(self.solve_response_v2, "fallback_reason", ""),
                },
            )
        except Exception as exc:
            logger.debug("Unable to build V2 decision snapshot: %s", exc)
            self.decision_snapshot_v2 = None

    def _build_solve_response_v2(self, action: str, result) -> SolveResponseV2:
        if isinstance(result, dict):
            payload = result
        elif hasattr(result, "to_dict") and callable(getattr(result, "to_dict")):
            payload = result.to_dict()
        elif hasattr(result, "__dict__"):
            payload = dict(result.__dict__)
        else:
            payload = {}
        normalized = dict(payload)
        metadata = dict(normalized.get("metadata") or {})
        is_legacy_result = bool(
            normalized.get("recommended_action")
            and not normalized.get("chosen_action")
            and not normalized.get("backend")
        )
        normalized.setdefault("chosen_action", action)
        if is_legacy_result:
            normalized["backend"] = "legacy_bridge"
            metadata.setdefault("solver_transport", self._last_solver_source)
        normalized["metadata"] = metadata
        solve_request_v2 = getattr(self, "solve_request_v2", None)
        normalized.setdefault(
            "preset_id",
            getattr(solve_request_v2, "tree_preset_id", "srp_hu_100bb") or "srp_hu_100bb",
        )
        response = SolveResponseV2.from_dict(normalized)
        metadata = dict(response.metadata)
        metadata.setdefault("bridge", "decisionmaker_gto")
        return SolveResponseV2(
            chosen_action=response.chosen_action,
            actions=response.actions,
            hero_ev=response.hero_ev,
            exploitability=response.exploitability,
            backend=response.backend,
            cache_tier=response.cache_tier,
            normalized_ranges=response.normalized_ranges,
            decision_confidence=response.decision_confidence,
            fallback_reason=response.fallback_reason,
            cache_hit=response.cache_hit,
            elapsed_ms=response.elapsed_ms,
            preset_id=response.preset_id,
            warnings=response.warnings,
            metadata=metadata,
        )

    def _call_gto_server_result(self, payload: dict):
        """
        Envoie une requête au serveur GTO Rust et retourne l'action recommandée.
        Retourne None si le serveur est inaccessible (fallback automatique).
        """
        try:
            ensure_local_gto_server()
            t0 = time.monotonic()
            response = requests.post(
                f"{GTO_SERVER_URL}/solve",
                json=payload,
                timeout=GTO_TIMEOUT_SEC
            )
            elapsed = time.monotonic() - t0

            if response.status_code == 200:
                data = response.json()
                self._last_solver_source = "http"
                logger.debug("GTO solve en %.0fms — action=%s EV=%.2f exploitabilité=%.3f",
                             elapsed * 1000,
                             data.get('recommended_action'),
                             data.get('hero_ev', 0),
                             data.get('exploitability', 0))
                return data
            else:
                logger.error("GTO server erreur %d: %s", response.status_code, response.text[:200])
                return None

        except requests.exceptions.ConnectionError:
            logger.warning("GTO server inaccessible (http://127.0.0.1:8765) — démarrer gto_server")
            return None
        except requests.exceptions.Timeout:
            logger.warning("GTO server timeout (%.0fs)", GTO_TIMEOUT_SEC)
            return None
        except Exception as e:
            logger.error("Erreur GTO server: %s", e)
            return None

    def _call_gto_server(self, payload: dict) -> Optional[str]:
        return self._extract_solver_action(self._call_gto_server_result(payload))

    def _call_gto_server_v2_result(self, solve_request: SolveRequestV2):
        try:
            ensure_local_gto_server()
            t0 = time.monotonic()
            response = requests.post(
                f"{GTO_SERVER_URL}/v2/solve",
                json=solve_request.to_dict(),
                timeout=GTO_TIMEOUT_SEC,
            )
            elapsed = time.monotonic() - t0
            response.raise_for_status()
            data = response.json()
            self._last_solver_source = "http"
            logger.debug(
                "GTO v2 solve en %.0fms — action=%s",
                elapsed * 1000,
                data.get("chosen_action") or data.get("recommended_action"),
            )
            return data
        except Exception as exc:
            logger.debug("GTO server v2 unavailable: %s", exc)
            return None

    def _call_native_gto_solver_result(self, payload: dict):
        """
        Essaie d'utiliser un binding Python natif (future PyO3 binding).
        Retourne None si le module n'existe pas, si l'appel échoue, ou si la
        réponse n'a pas de champ d'action exploitable.
        """
        for module_name in NATIVE_GTO_MODULE_CANDIDATES:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("Native GTO import failed for %s: %s", module_name, exc)
                continue

            solver_fn = None
            for fn_name in NATIVE_GTO_FUNCTION_CANDIDATES:
                solver_fn = getattr(module, fn_name, None)
                if callable(solver_fn):
                    break

            if solver_fn is None:
                logger.debug("Native GTO module %s found but no solver entrypoint", module_name)
                continue

            try:
                result = solver_fn(**payload)
            except TypeError:
                try:
                    result = solver_fn(payload)
                except Exception as exc:
                    logger.debug("Native GTO call failed for %s: %s", module_name, exc)
                    continue
            except Exception as exc:
                logger.debug("Native GTO call failed for %s: %s", module_name, exc)
                continue

            action = self._extract_solver_action(result)
            if action:
                self._last_solver_source = "native"
                logger.debug("Native GTO solve via %s returned action=%s", module_name, action)
                return result

            logger.debug("Native GTO solve via %s returned no usable action", module_name)

        return None

    def _call_native_gto_solver_v2_result(self, solve_request: SolveRequestV2):
        request_dict = solve_request.to_dict()
        kwargs = {
            "spot_id": solve_request.spot_id or None,
            "hero_range": solve_request.hero_range,
            "villain_ranges": list(solve_request.villain_ranges),
            "board": list(solve_request.board),
            "starting_pot": solve_request.starting_pot,
            "effective_stack": solve_request.effective_stack,
            "hero_position": solve_request.hero_position or None,
            "action_history": list(solve_request.action_history),
            "tree_preset_id": solve_request.tree_preset_id or None,
            "rake": solve_request.rake,
            "num_players": solve_request.num_players,
            "legal_actions": [action.name for action in solve_request.legal_actions],
            "cache_policy": getattr(solve_request.cache_policy, "value", str(solve_request.cache_policy)),
            "hero_confidence": solve_request.hero_confidence,
            "state_confidence": solve_request.state_confidence,
            "use_cache": solve_request.use_cache,
            "time_budget_ms": solve_request.time_budget_ms,
        }
        legacy_payload = self._build_legacy_solver_payload(solve_request)

        for module_name in NATIVE_GTO_MODULE_CANDIDATES:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("Native GTO import failed for %s: %s", module_name, exc)
                continue

            solver_v2 = getattr(module, "solve_spot_v2", None)
            if callable(solver_v2):
                try:
                    result = solver_v2(**kwargs)
                except TypeError:
                    try:
                        result = solver_v2(request_dict)
                    except Exception as exc:
                        logger.debug("Native GTO v2 call failed for %s: %s", module_name, exc)
                    else:
                        if self._extract_solver_action(result):
                            self._last_solver_source = "native"
                            return result
                except Exception as exc:
                    logger.debug("Native GTO v2 call failed for %s: %s", module_name, exc)
                else:
                    if self._extract_solver_action(result):
                        self._last_solver_source = "native"
                        return result
        return self._call_native_gto_solver_result(legacy_payload)

    def _call_native_gto_solver(self, payload: dict) -> Optional[str]:
        return self._extract_solver_action(self._call_native_gto_solver_result(payload))

    def _extract_solver_action(self, result) -> Optional[str]:
        """
        Normalise plusieurs formes de retour possibles du binding natif.
        """
        if result is None:
            return None

        if isinstance(result, str):
            return result

        if isinstance(result, (list, tuple)):
            if result and isinstance(result[0], str):
                return result[0]
            return None

        if isinstance(result, dict):
            for key in (
                "chosen_action",
                "recommended_action",
                "action",
                "best_action",
                "selected_action",
            ):
                value = result.get(key)
                if isinstance(value, str) and value:
                    return value
            return None

        for attr in ("chosen_action", "recommended_action", "action", "best_action", "selected_action"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value:
                return value

        return None

    def _solve_postflop_result(self, payload: dict):
        """
        Ordre de priorité:
        1. binding Python natif
        2. serveur HTTP local
        3. fallback original
        """
        result = self._call_native_gto_solver_result(payload)
        if result is not None:
            return result
        return self._call_gto_server_result(payload)

    def _solve_postflop_action(self, payload: dict) -> Optional[str]:
        return self._extract_solver_action(self._solve_postflop_result(payload))

    def _set_no_action(self, reason: str, warnings: tuple[str, ...] = ()) -> None:
        self._last_solver_source = "gate"
        self.decision = "NoAction"
        self.finalCallLimit = 0.0
        self.finalBetLimit = 0.0
        self.solve_response_v2 = SolveResponseV2(
            chosen_action="no_action",
            actions=(),
            hero_ev=0.0,
            exploitability=0.0,
            backend="decision_gate",
            cache_tier=CacheTier.NONE,
            normalized_ranges=(),
            decision_confidence=0.0,
            fallback_reason=reason,
            cache_hit=False,
            elapsed_ms=0,
            preset_id=getattr(self.solve_request_v2, "tree_preset_id", "srp_hu_100bb") or "srp_hu_100bb",
            warnings=warnings or ("decision_gate_blocked",),
            metadata={"reason": reason},
        )
        self._record_decision_snapshot("gate", warnings=warnings or ("decision_gate_blocked",))

    def _resolve_snapshot_source(self, source: str) -> str:
        response = getattr(self, "solve_response_v2", None)
        if response is None:
            return source

        backend = str(getattr(response, "backend", "") or "")
        cache_tier = getattr(getattr(response, "cache_tier", None), "value", getattr(response, "cache_tier", ""))
        fallback_reason = str(getattr(response, "fallback_reason", "") or "")
        chosen_action = str(getattr(response, "chosen_action", "") or "")

        if backend == "decision_gate":
            return "gate"
        if backend == "fallback" or (not chosen_action and fallback_reason):
            return "fallback"
        if str(cache_tier or "") == "disk":
            return "cache"
        if backend:
            return backend
        return source

    def _decide_preflop(self) -> None:
        """Délègue à la classe Decision originale de dickreuter pour le preflop."""
        if self._delegate_to_original_decision():
            self._record_decision_snapshot("legacy")
            return
        # Fallback minimal
        self._apply_runtime_decision(DecisionTypes.fold)
        self._record_decision_snapshot("fallback", warnings=("preflop_fallback",))

    def _decide_postflop_fallback(self) -> None:
        """
        Fallback si le solver GTO est indisponible :
        utilise l'équité Monte Carlo déjà calculée par dickreuter (t.equity).
        """
        if self._delegate_to_original_decision():
            logger.warning("Falling back to the original decision maker")
            self._record_decision_snapshot("legacy", warnings=("fallback_used",))
            return

        equity = getattr(self.t, 'equity', 0.5) or 0.5
        has_check = getattr(self.t, 'checkButton', False)
        min_call  = getattr(self.t, 'minCall', 0) or 0

        logger.warning("Fallback equity-based (equity=%.2f)", equity)

        if equity > 0.65:
            self._apply_runtime_decision(DecisionTypes.bet3)    # bet half pot
        elif equity > 0.50:
            self._apply_runtime_decision(DecisionTypes.call if min_call > 0 else DecisionTypes.check)
        elif equity > 0.35:
            self._apply_runtime_decision(DecisionTypes.check if has_check else DecisionTypes.fold)
        else:
            self._apply_runtime_decision(DecisionTypes.fold)
        self._record_decision_snapshot("fallback", warnings=("fallback_used",))

    def _delegate_to_original_decision(self) -> bool:
        """Try to reuse the original dickreuter decision maker."""
        if OriginalDecisionMaker is None:
            return False

        try:
            original = OriginalDecisionMaker(self.t, self.h, self.p, self.l)
            original.make_decision(self.t, self.h, self.p, self.l)
            self.decision = original.decision
            self.finalCallLimit = getattr(original, 'finalCallLimit', 0.0)
            self.finalBetLimit = getattr(original, 'finalBetLimit', 0.0)
            self.maxCallEV = getattr(original, 'maxCallEV', 0.0)
            self.outs = getattr(original, 'outs', 0)
            self.pot_multiple = getattr(original, 'pot_multiple', 0.0)
            return True
        except Exception as exc:
            logger.error("Erreur Decision original: %s", exc)
            return False


Decision = DecisionGTO
DecisionMakerGTO = DecisionGTO


# ─── Test rapide standalone ───────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.DEBUG)

    # Simuler un appel direct au serveur GTO (sans objet table)
    payload = {
        "oop_range": "AsKh",
        "ip_range": "AA,KK,QQ,JJ,AKs,AQs",
        "board": ["Ah", "Kd", "3c"],
        "starting_pot": 12.0,
        "effective_stack": 88.0,
        "hero_is_oop": True,
        "max_iterations": 100,
        "target_exploitability": 1.0,
    }

    demo = DecisionGTO.__new__(DecisionGTO)
    action = demo._solve_postflop_action(payload)
    if action:
        print(json.dumps({"recommended_action": action}, indent=2))
    else:
        print("Aucun solveur natif/HTTP disponible")
