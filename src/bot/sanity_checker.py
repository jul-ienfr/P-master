import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SanityChecker")


@dataclass(frozen=True)
class ActionIntent:
    action: str
    bet_size: Optional[float] = None
    source: str = "unknown"

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "ActionIntent":
        payload = payload or {}
        action = str(payload.get("action", "FOLD") or "FOLD").upper()

        raw_bet_size = payload.get("bet_size")
        bet_size: Optional[float] = None
        if raw_bet_size is not None:
            try:
                bet_size = float(raw_bet_size)
            except (TypeError, ValueError):
                bet_size = None

        return cls(
            action=action,
            bet_size=bet_size,
            source=str(payload.get("source", "unknown") or "unknown")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "bet_size": self.bet_size,
            "source": self.source,
        }


@dataclass(frozen=True)
class GateReason:
    code: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    status: str
    reasons: List[GateReason] = field(default_factory=list)
    action_intent: Optional[ActionIntent] = None
    confidence: Optional[float] = None

    @property
    def reason(self) -> str:
        if self.reasons:
            return self.reasons[0].code
        if self.allowed:
            return "ready"
        return self.status or "blocked"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "confidence": self.confidence,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "action_intent": self.action_intent.to_dict() if self.action_intent else None,
        }

class SanityChecker:
    """
    Bouclier logique contre les hallucinations de l'IA (YOLO/OCR).
    VÃ©rifie que les donnÃ©es lues sur l'Ã©cran respectent les rÃ¨gles mathÃ©matiques du Poker.
    """
    def __init__(self):
        self.max_pot_allowed = 200000.0  # SÃ©curitÃ© hardcodÃ©e (ex: NL100, pot max thÃ©orique)

        # Ocr Reconciliation state variables
        self._pot_discrepancy_count = 0
        self._last_ocr_pot = -1.0
        self.stack_ocr_quarantine_seconds = 1.0
        self.stack_ocr_warning_cooldown_seconds = 1.0
        self._stack_ocr_quarantine_until: Dict[str, float] = {}
        self._stack_ocr_warning_last_at: Dict[str, float] = {}

    @staticmethod
    def _stack_context_key(seat_id: Optional[str]) -> str:
        return str(seat_id or "").strip()

    def reset_ocr_quarantine(self) -> None:
        self._stack_ocr_quarantine_until.clear()
        self._stack_ocr_warning_last_at.clear()

    def reset_pot_reconciliation(self) -> None:
        self._pot_discrepancy_count = 0
        self._last_ocr_pot = -1.0

    def get_stack_read_quarantine_remaining(self, seat_id: Optional[str]) -> float:
        key = self._stack_context_key(seat_id)
        if not key:
            return 0.0

        blocked_until = float(self._stack_ocr_quarantine_until.get(key, 0.0) or 0.0)
        now = time.monotonic()
        if blocked_until <= now:
            self._stack_ocr_quarantine_until.pop(key, None)
            return 0.0
        return blocked_until - now

    def is_stack_read_quarantined(self, seat_id: Optional[str]) -> bool:
        return self.get_stack_read_quarantine_remaining(seat_id) > 0.0

    def _register_stack_ocr_anomaly(self, seat_id: Optional[str], message: str) -> None:
        key = self._stack_context_key(seat_id)
        if not key:
            logger.warning(message)
            return

        now = time.monotonic()
        self._stack_ocr_quarantine_until[key] = max(
            float(self._stack_ocr_quarantine_until.get(key, 0.0) or 0.0),
            now + self.stack_ocr_quarantine_seconds,
        )
        last_warning_at = float(self._stack_ocr_warning_last_at.get(key, float("-inf")) or float("-inf"))
        if (now - last_warning_at) >= self.stack_ocr_warning_cooldown_seconds:
            logger.warning(message)
            self._stack_ocr_warning_last_at[key] = now

    def mark_stack_read_recovered(self, seat_id: Optional[str]) -> None:
        key = self._stack_context_key(seat_id)
        if not key:
            return
        self._stack_ocr_quarantine_until.pop(key, None)
        self._stack_ocr_warning_last_at.pop(key, None)

    def is_possible_new_hand_pot(self, old_pot: float, new_ocr_pot: float) -> bool:
        try:
            old_pot = float(old_pot or 0.0)
        except (TypeError, ValueError):
            old_pot = 0.0

        try:
            new_ocr_pot = float(new_ocr_pot or 0.0)
        except (TypeError, ValueError):
            new_ocr_pot = 0.0

        if old_pot <= 0.0 or new_ocr_pot >= old_pot:
            return False
        if new_ocr_pot == 0.0:
            return True
        return new_ocr_pot <= 5.0

    def is_possible_board_reset(self, old_board: List[str], new_board: List[str]) -> bool:
        return len(old_board or []) > 0 and len(new_board or []) < len(old_board or [])

    def is_same_hand_board_transition(self, old_board: List[str], new_board: List[str]) -> bool:
        old_board = list(old_board or [])
        new_board = list(new_board or [])

        if abs(len(new_board) - len(old_board)) != 1:
            return False

        if len(new_board) > len(old_board):
            return new_board[:len(old_board)] == old_board

        return old_board[:len(new_board)] == new_board

    def requires_multiframe_street_confirmation(
        self,
        current_street: str,
        candidate_street: str,
        current_board: List[str],
        new_board: List[str],
    ) -> bool:
        expected_board_size = {"FLOP": 3, "TURN": 4, "RIVER": 5}
        current_street = str(current_street or "IDLE")
        candidate_street = str(candidate_street or current_street)
        current_board = list(current_board or [])
        new_board = list(new_board or [])

        if candidate_street not in {"TURN", "RIVER"}:
            return False
        if expected_board_size.get(candidate_street) != len(new_board):
            return False

        street_order = {"IDLE": 0, "PREFLOP": 1, "FLOP": 2, "TURN": 3, "RIVER": 4, "SHOWDOWN": 5}
        if street_order.get(candidate_street, -1) <= street_order.get(current_street, -1):
            return False

        return len(new_board) == len(current_board) + 1

    def evaluate_action_gate(
        self,
        action_intent: ActionIntent,
        tracker_state: Optional[Dict[str, Any]],
        coords_mapping: Optional[Dict[str, Any]],
        on_failure=None,
    ) -> GateResult:
        reasons: List[GateReason] = []
        tracker_state = tracker_state or {}
        coords_mapping = coords_mapping or {}

        hero_cards = tracker_state.get("hero_cards") or []
        board = tracker_state.get("board") or []
        pot = tracker_state.get("pot", 0.0)
        street = tracker_state.get("street", "IDLE")
        legal_actions = [str(action).upper() for action in (tracker_state.get("legal_actions") or [])]
        in_hand = bool(tracker_state.get("in_hand", False))
        state_confidence = float(tracker_state.get("state_confidence", 0.0) or 0.0)

        if state_confidence < 0.45:
            reasons.append(GateReason(
                code="LOW_STATE_CONFIDENCE",
                message="La confiance globale de l'etat live est trop faible.",
                context={"state_confidence": state_confidence}
            ))

        if not in_hand:
            reasons.append(GateReason(
                code="NOT_IN_HAND",
                message="Aucune main active n'est confirmÃ©e.",
                context={"street": street}
            ))

        if len(hero_cards) != 2:
            reasons.append(GateReason(
                code="HERO_CARDS_UNCERTAIN",
                message="Le bot ne confirme pas exactement deux cartes hero.",
                context={"hero_cards_count": len(hero_cards)}
            ))

        if len(board) not in (0, 3, 4, 5):
            reasons.append(GateReason(
                code="BOARD_UNCERTAIN",
                message="Le board lu est incoherent pour une street valide.",
                context={"board_count": len(board), "board": board}
            ))

        expected_street_by_board = {0: "PREFLOP", 3: "FLOP", 4: "TURN", 5: "RIVER"}
        expected_street = expected_street_by_board.get(len(board))
        if in_hand and expected_street and street not in (expected_street, "SHOWDOWN"):
            reasons.append(GateReason(
                code="STATE_INCOHERENT",
                message="La street du tracker ne correspond pas au board observe.",
                context={"street": street, "expected_street": expected_street, "board_count": len(board)}
            ))

        try:
            numeric_pot = float(pot)
        except (TypeError, ValueError):
            numeric_pot = -1.0

        if numeric_pot < 0 or numeric_pot > self.max_pot_allowed:
            reasons.append(GateReason(
                code="POT_UNCERTAIN",
                message="Le pot courant est absent ou hors bornes de securite.",
                context={"pot": pot, "max_pot_allowed": self.max_pot_allowed}
            ))

        if board and numeric_pot <= 0:
            reasons.append(GateReason(
                code="MISSING_POSTFLOP_POT",
                message="Board detecte sans pot fiable.",
                context={"board_count": len(board), "pot": pot}
            ))

        if legal_actions:
            base_actions = {
                "RAISE_HALF": "RAISE",
                "RAISE_POT": "RAISE",
                "BET": "BET",
                "ALL_IN": "ALL_IN",
                "CALL": "CALL",
                "CHECK": "CHECK",
                "FOLD": "FOLD",
                "RAISE": "RAISE",
            }
            action_base = base_actions.get(action_intent.action, action_intent.action)
            is_legal = any(action_base in legal for legal in legal_actions) or action_intent.action in legal_actions
            if not is_legal:
                reasons.append(GateReason(
                    code="ILLEGAL_ACTION",
                    message="L'action demandee n'appartient pas aux actions autorisees.",
                    context={"action": action_intent.action, "legal_actions": legal_actions}
                ))

        if action_intent.action in {"BET", "RAISE", "RAISE_HALF", "RAISE_POT", "ALL_IN"} and action_intent.bet_size is None:
            reasons.append(GateReason(
                code="BET_SIZE_MISSING",
                message="Une action de mise exige un montant explicite.",
                context={"action": action_intent.action}
            ))

        required_coords = self._required_coordinates_for_action(action_intent.action)
        missing_coords = [coord for coord in required_coords if not coords_mapping.get(coord)]
        if missing_coords:
            reasons.append(GateReason(
                code="MISSING_COORDINATES",
                message="Les coordonnees d'execution live sont incompletes.",
                context={"action": action_intent.action, "missing": missing_coords}
            ))

        if reasons:
            gate_result = GateResult(
                allowed=False,
                status="blocked" if any(reason.code in {"STATE_INCOHERENT", "ILLEGAL_ACTION", "MISSING_COORDINATES", "NOT_IN_HAND"} for reason in reasons) else "uncertain",
                reasons=reasons,
                action_intent=action_intent,
                confidence=state_confidence,
            )
            logger.warning(
                "Gate runtime refuse l'action %s: %s",
                action_intent.action,
                ", ".join(reason.code for reason in reasons),
            )
            if callable(on_failure):
                try:
                    on_failure(gate_result)
                except Exception as exc:
                    logger.debug("Callback on_failure ignoree: %s", exc)
            return gate_result

        return GateResult(
            allowed=True,
            status="allowed",
            reasons=[],
            action_intent=action_intent,
            confidence=state_confidence,
        )

    def _required_coordinates_for_action(self, action_name: str) -> List[str]:
        if action_name == "FOLD":
            return ["FOLD"]
        if action_name in {"CALL", "CHECK"}:
            return ["CALL"]
        if action_name in {"BET", "RAISE", "RAISE_HALF", "RAISE_POT", "ALL_IN"}:
            return ["BET_BOX", "BET_BTN"]
        return []
        
    def validate_pot_evolution(self, old_pot: float, new_ocr_pot: float, total_bets: float, *, allow_unbacked_observed_pot: bool = False) -> float:
        """
        VÃ©rifie si le nouveau pot lu par l'OCR est mathÃ©matiquement possible.
        old_pot: Le pot Ã  la frame N-1
        new_ocr_pot: Le pot lu par l'OCR Ã  la frame N
        total_bets: La somme des mises dÃ©tectÃ©es (chute des stacks des joueurs)
        """
        try:
            old_pot = max(0.0, float(old_pot or 0.0))
        except (TypeError, ValueError):
            old_pot = 0.0

        try:
            new_ocr_pot = max(0.0, float(new_ocr_pot or 0.0))
        except (TypeError, ValueError):
            new_ocr_pot = 0.0

        try:
            total_bets = max(0.0, float(total_bets or 0.0))
        except (TypeError, ValueError):
            total_bets = 0.0

        # Si c'est une nouvelle main (pot retombe Ã  0 ou blindes)
        if self.is_possible_new_hand_pot(old_pot, new_ocr_pot):
            self.reset_pot_reconciliation()
            self._last_ocr_pot = new_ocr_pot
            return new_ocr_pot

        # Calcul du pot thÃ©orique exact
        expected_pot = old_pot + total_bets

        # Tant qu'aucun pot mathÃ©matique stable n'existe encore, un gros pot OCR isolÃ©
        # provient presque toujours d'un faux positif visuel pendant une phase d'observation.
        if expected_pot <= 0.0 and new_ocr_pot > 5.0 and not allow_unbacked_observed_pot:
            self.reset_pot_reconciliation()
            self._last_ocr_pot = new_ocr_pot
            logger.warning(
                "Pic OCR ignorÃ© sans contexte stable ! Pot lu: %s | Pot mathÃ©matique attendu: %s.",
                new_ocr_pot,
                expected_pot,
            )
            return 0.0

        if expected_pot <= 0.0 and new_ocr_pot > 5.0 and allow_unbacked_observed_pot:
            self.reset_pot_reconciliation()
            self._last_ocr_pot = new_ocr_pot
            return new_ocr_pot

        # TolÃ©rance de lecture (ex: le rake du casino a Ã©tÃ© prÃ©levÃ©, ou un ante non vu)
        # On accepte une marge d'erreur de +/- 5% ou 1 blinde
        margin_of_error = max(expected_pot * 0.05, 2.0)

        if abs(new_ocr_pot - expected_pot) <= margin_of_error:
            # L'OCR est cohÃ©rent avec la rÃ©alitÃ© mathÃ©matique
            self.reset_pot_reconciliation()
            self._last_ocr_pot = new_ocr_pot
            return new_ocr_pot

        # STATE RECONCILIATION: OCR diverges from math.
        if new_ocr_pot == self._last_ocr_pot:
            self._pot_discrepancy_count += 1
        else:
            self._pot_discrepancy_count = 1
            self._last_ocr_pot = new_ocr_pot

        # If OCR is consistent for 3 consecutive reads, we trust it and reconcile
        if self._pot_discrepancy_count >= 3:
            logger.info(f"ðŸ”„ RÃ©conciliation Pot : L'OCR insiste depuis 3 frames, synchronisation mathÃ©matique sur la valeur OCR au lieu de forcer. (Ancien math={expected_pot}, Nouvel OCR={new_ocr_pot})")
            self.reset_pot_reconciliation()
            self._last_ocr_pot = new_ocr_pot
            return new_ocr_pot

        if new_ocr_pot > expected_pot:
            logger.warning(f"âš ï¸ Pic OCR dÃ©tectÃ© ! Pot lu: {new_ocr_pot} | Pot mathÃ©matique attendu: {expected_pot}. Bufferisation en cours...")
            return expected_pot

        # NEW CODE: Anti-deflation
        if expected_pot > 0 and new_ocr_pot < expected_pot and (new_ocr_pot / expected_pot) < 0.5:
            logger.warning(f"âš ï¸ Anomalie OCR bloquÃ©e ! Pot lu ({new_ocr_pot}) trop bas par rapport au pot mathÃ©matique ({expected_pot}).")
            return expected_pot

        # Un pot OCR trop bas est souvent un retard de lecture ou une mise partiellement observÃ©e.
        # On conserve la valeur OCR pour Ã©viter d'inventer des jetons et de dÃ©clencher des resets parasites.
        return new_ocr_pot

    def validate_stack_read(
        self,
        current_stack: float,
        new_ocr_stack: float,
        starting_stack: float,
        current_bet: float,
        seat_id: Optional[str] = None,
    ) -> float:
        """
        Vérifie qu'un joueur n'a pas soudainement gagné des jetons au milieu d'une main.
        Retourne le nouveau stack s'il est valide, sinon l'ancien (current_stack).
        """
        del current_bet

        if new_ocr_stack <= 0.0:
            # A transient OCR miss should not be interpreted as an all-in.
            if current_stack > starting_stack > 0.0:
                return starting_stack
            return current_stack if current_stack > 0.0 else 0.0

        # Bootstrap OCR: si on n'a encore jamais eu de stack fiable pour ce siège,
        # on accepte la première lecture positive au lieu de la bloquer comme une hallucination.
        if starting_stack <= 0.0:
            self.mark_stack_read_recovered(seat_id)
            return new_ocr_stack

        if new_ocr_stack > starting_stack + 0.1: # +0.1 pour float rounding
            self._register_stack_ocr_anomaly(
                seat_id,
                f"⚠️ Anomalie Stack bloquée ! Stack lu: {new_ocr_stack} > Stack de départ: {starting_stack}. L'OCR a halluciné des jetons.",
            )
            return current_stack

        # Anti-"Phantom bet" - Si la chute de stack est aberrante (ex: de 100 à 1 en une frame)
        # On suppose souvent une erreur OCR (virgule ratée, digit masqué)
        if current_stack > 0:
            drop_ratio = new_ocr_stack / current_stack
            amount_dropped = current_stack - new_ocr_stack

            # Si le stack chute brutalement de plus de 85% de sa valeur ET qu'il reste très peu de jetons
            # ou si on voit une baisse minuscule (moins de la petite blinde, souvent erreur virgule OCR)
            if (drop_ratio < 0.15 and amount_dropped > max(5.0, (current_stack + amount_dropped) * 0.05)) or (0 < amount_dropped < 0.02):
                self._register_stack_ocr_anomaly(
                    seat_id,
                    f"⚠️ Chute de stack bloquée (Drop suspect lu OCR) ! Ancien: {current_stack} -> Lu: {new_ocr_stack}",
                )
                return current_stack

            # Anti-bruit pour les gros stacks (Argent fictif / Gros pots)
            if 0 < amount_dropped < 10.0 and current_stack > 1000.0:
                self._register_stack_ocr_anomaly(
                    seat_id,
                    f"⚠️ Micro-fluctuation bloquée ! Ancien: {current_stack} -> Lu: {new_ocr_stack} (Bruit OCR ignoré)",
                )
                return current_stack

        self.mark_stack_read_recovered(seat_id)
        return new_ocr_stack

    def is_suspect_stack_drop(self, current_stack: float, clean_stack: float, pot: float) -> bool:
        """
        Returns True when a stack drop looks large enough to warrant temporal
        confirmation (i.e. seeing the same value on a second frame) before it
        is consumed as a bet.  Small / expected drops pass through immediately.
        """
        if current_stack <= 0.0 or clean_stack >= current_stack:
            return False
        amount_dropped = current_stack - clean_stack
        drop_ratio = amount_dropped / current_stack
        effective_pot = max(pot, 1.0)
        # A drop is suspect when it exceeds half the current stack
        # OR exceeds 3x the pot (an implausible single-action sizing).
        return drop_ratio > 0.50 or amount_dropped > effective_pot * 3.0
        
    def validate_board_cards(self, current_stage: str, detected_cards: list) -> list:
        """
        Filtre les cartes "fantÃ´mes" (erreurs YOLO ou animations) selon la street.
        """
        num_cards = len(detected_cards)
        
        if current_stage in {"IDLE", "PREFLOP"} and num_cards not in (0, 3):
            logger.debug(f"Cartes ignorÃ©es avant le flop (frame instable) : {detected_cards}")
            return []
        elif current_stage == "FLOP" and num_cards != 3:
            # Si on est au flop, il DOIT y avoir 3 cartes. Si YOLO en voit 2 ou 4, c'est une erreur de frame.
            logger.debug(f"Frame instable au Flop. YOLO voit {num_cards} cartes. Attente de stabilisation...")
            return self._coerce_board_count(detected_cards, 3)
        elif current_stage == "TURN" and num_cards not in (3, 4):
            logger.debug(f"Frame instable au Turn. YOLO voit {num_cards} cartes.")
            return self._coerce_board_count(detected_cards, 4)
        elif current_stage == "RIVER" and num_cards not in (4, 5):
            logger.debug(f"Frame instable a la River. YOLO voit {num_cards} cartes.")
            return self._coerce_board_count(detected_cards, 5)
        
        return detected_cards

    def _coerce_board_count(self, detected_cards: list, expected_count: int) -> list:
        if len(detected_cards) < expected_count:
            return detected_cards
        return list(detected_cards[:expected_count])

