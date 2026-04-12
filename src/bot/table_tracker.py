import logging
from collections import deque
from typing import List, Dict, Optional, Any
from pydantic import BaseModel

try:
    from transitions import Machine
except ImportError:
    Machine = None

# Import du bouclier anti-hallucination
from src.bot.sanity_checker import SanityChecker
from src.bot.live_reconstruction import smooth_state_confidence_window, stable_window_value

logger = logging.getLogger("TableTracker")


class _FallbackMachine:
    def __init__(self, model, states: List[str], initial: str):
        self.model = model
        self.states = set(states)
        self.model.state = initial
        self._transitions: dict[str, list[tuple[set[str] | str, str]]] = {}

    def add_transition(self, trigger: str, source, dest: str):
        sources = source if source == '*' else {source} if isinstance(source, str) else set(source)
        self._transitions.setdefault(trigger, []).append((sources, dest))

        def _trigger():
            current = getattr(self.model, "state", None)
            for allowed_sources, target in self._transitions.get(trigger, []):
                if allowed_sources == '*' or current in allowed_sources:
                    self.model.state = target
                    return True
            return False

        setattr(self.model, trigger, _trigger)

class PlayerState(BaseModel):
    seat_id: str
    seat_index: int = -1
    name: str
    starting_stack: float
    current_stack: float
    bet: float = 0.0
    is_active: bool = True
    has_folded: bool = False
    is_hero: bool = False
    has_button: bool = False
    position: str = "UNKNOWN" # UTG, HJ, CO, BTN, SB, BB

class TableTracker:
    # Définition des états officiels du Poker
    states = ['IDLE', 'PREFLOP', 'FLOP', 'TURN', 'RIVER', 'SHOWDOWN']

    _STREET_ORDER = {state: index for index, state in enumerate(states)}
    _BOARD_STREET_BY_SIZE = {0: 'PREFLOP', 3: 'FLOP', 4: 'TURN', 5: 'RIVER'}

    def __init__(self, db_manager):
        self.db = db_manager
        self.sanity = SanityChecker()
        
        # --- 1. Machine à États Stricte (Transitions) ---
        machine_cls = Machine or _FallbackMachine
        self.machine = machine_cls(model=self, states=TableTracker.states, initial='IDLE')
        
        # Règles de passage (impossible de passer de PREFLOP à RIVER)
        self.machine.add_transition(trigger='deal_hole_cards', source='IDLE', dest='PREFLOP')
        self.machine.add_transition(trigger='deal_flop', source='PREFLOP', dest='FLOP')
        self.machine.add_transition(trigger='deal_turn', source='FLOP', dest='TURN')
        self.machine.add_transition(trigger='deal_river', source='TURN', dest='RIVER')
        self.machine.add_transition(trigger='end_hand', source='*', dest='IDLE')
        
        # État courant de la table
        self.current_board: List[str] = []
        self.pot_total: float = 0.0
        self.players: Dict[str, PlayerState] = {}
        self.hero_cards: List[str] = []
        self.legal_actions: List[str] = []
        self.action_buttons: List[str] = []
        self.spot_id: str = ""
        self.state_confidence: float = 0.0
        
        self.last_pot: float = 0.0
        self.current_hand_actions: List[Dict[str, Any]] = []
        self.observed_players_this_hand: set[str] = set()
        self.pending_new_hand_pot: Optional[float] = None
        self.pending_new_hand_frames: int = 0
        self.pending_board_reset: Optional[List[str]] = None
        self.pending_board_reset_frames: int = 0
        self.pending_street_promotion: Optional[str] = None
        self.pending_street_promotion_board: Optional[List[str]] = None
        self.pending_street_promotion_frames: int = 0
        self._recent_state_confidences = deque(maxlen=3)
        self._recent_hero_seat_ids = deque(maxlen=3)

    def reset_for_new_hand(self):
        """Réinitialise l'état et force la State Machine à IDLE."""
        if self.state != 'IDLE':
            self.end_hand()
            
        self.current_board = []
        self.hero_cards = []
        self.pot_total = 0.0
        self.last_pot = 0.0
        self.legal_actions = []
        self.action_buttons = []
        self.spot_id = ""
        self.state_confidence = 0.0
        self.current_hand_actions = []
        self.observed_players_this_hand = set()
        self.pending_new_hand_pot = None
        self.pending_new_hand_frames = 0
        self.pending_board_reset = None
        self.pending_board_reset_frames = 0
        self.pending_street_promotion = None
        self.pending_street_promotion_board = None
        self.pending_street_promotion_frames = 0
        self._recent_state_confidences.clear()
        self._recent_hero_seat_ids.clear()
        
        for p in self.players.values():
            p.is_active = True
            p.has_folded = False
            p.bet = 0.0
            p.starting_stack = p.current_stack # Snapshot du stack en début de main
            
        logger.info(f"--- Nouvelle Main Détectée (État: {self.state}) ---")

    def _advance_to_street(self, target_street: str):
        while self.state != target_street:
            if self.state == 'IDLE' and target_street in {'PREFLOP', 'FLOP', 'TURN', 'RIVER'}:
                self.deal_hole_cards()
            elif self.state == 'PREFLOP' and target_street in {'FLOP', 'TURN', 'RIVER'}:
                self.deal_flop()
            elif self.state == 'FLOP' and target_street in {'TURN', 'RIVER'}:
                self.deal_turn()
            elif self.state == 'TURN' and target_street == 'RIVER':
                self.deal_river()
            else:
                break

    def _parse_seat_index(self, vision_player: dict) -> Optional[int]:
        seat_index = vision_player.get('seat_index')
        if seat_index is None:
            return None
        return int(seat_index)

    def _resolve_board_stage_hint(self, raw_board: list[str]) -> Optional[str]:
        board_size = len(raw_board)
        hinted_stage = self._BOARD_STREET_BY_SIZE.get(board_size)
        if hinted_stage is None:
            return None
        if board_size == 0 or board_size <= len(self.current_board):
            return hinted_stage
        if raw_board[:len(self.current_board)] == self.current_board:
            return hinted_stage
        return None

    def _resolve_confirmed_target_street(self, incoming_street: str, board_stage_hint: Optional[str], new_board: List[str]) -> str:
        target_street = self.state
        for street_hint in (incoming_street, board_stage_hint):
            if street_hint not in TableTracker.states:
                continue
            if self._STREET_ORDER[street_hint] <= self._STREET_ORDER[target_street]:
                continue
            expected_board_size = {"IDLE": 0, "PREFLOP": 0, "FLOP": 3, "TURN": 4, "RIVER": 5}.get(street_hint)
            if expected_board_size is None or len(new_board) == expected_board_size:
                target_street = street_hint

        if target_street == self.state:
            self.pending_street_promotion = None
            self.pending_street_promotion_board = None
            self.pending_street_promotion_frames = 0
            return target_street

        if not self.sanity.requires_multiframe_street_confirmation(
            self.state,
            target_street,
            self.current_board,
            new_board,
        ):
            self.pending_street_promotion = None
            self.pending_street_promotion_board = None
            self.pending_street_promotion_frames = 0
            return target_street

        if self.pending_street_promotion == target_street and self.pending_street_promotion_board == list(new_board):
            self.pending_street_promotion_frames += 1
        else:
            self.pending_street_promotion = target_street
            self.pending_street_promotion_board = list(new_board)
            self.pending_street_promotion_frames = 1

        if self.pending_street_promotion_frames >= 2:
            self.pending_street_promotion = None
            self.pending_street_promotion_board = None
            self.pending_street_promotion_frames = 0
            return target_street

        return self.state

    def _should_reuse_previous_legal_actions(
        self,
        incoming_street: str,
        raw_board: List[str],
        hero_cards: List[str],
        incoming_legal_actions: List[str],
        incoming_action_buttons: List[str],
    ) -> bool:
        return (
            not incoming_legal_actions
            and not incoming_action_buttons
            and bool(self.legal_actions)
            and incoming_street == self.state
            and list(raw_board) == self.current_board
            and len(hero_cards) == 2
            and hero_cards == self.hero_cards
        )

    def _smooth_state_confidence(
        self,
        incoming_confidence: float,
        incoming_street: str,
        raw_board: List[str],
        hero_cards: List[str],
    ) -> float:
        same_runtime_context = (
            incoming_street == self.state
            and list(raw_board) == self.current_board
            and hero_cards == self.hero_cards
        )
        if not same_runtime_context:
            self._recent_state_confidences.clear()
            return round(incoming_confidence, 3)

        return smooth_state_confidence_window(list(self._recent_state_confidences), incoming_confidence)

    def _smooth_hero_flags(self, vision_players: List[dict]) -> List[dict]:
        if not vision_players:
            self._recent_hero_seat_ids.clear()
            return vision_players

        available_seat_ids = {
            str(player.get("seat_id") or player.get("name") or "")
            for player in vision_players
        }

        incoming_hero_seat_id = next(
            (
                str(player.get("seat_id") or player.get("name") or "")
                for player in vision_players
                if bool(player.get("is_hero", False))
            ),
            "",
        )
        previous_hero_seat_id = self._recent_hero_seat_ids[-1] if self._recent_hero_seat_ids else ""
        if (
            previous_hero_seat_id
            and previous_hero_seat_id in available_seat_ids
            and incoming_hero_seat_id
            and incoming_hero_seat_id != previous_hero_seat_id
        ):
            stable_hero_seat_id = previous_hero_seat_id
        else:
            stable_hero_seat_id = stable_window_value(
                list(self._recent_hero_seat_ids),
                incoming_hero_seat_id,
                ignore_values=("",),
            )

        if not stable_hero_seat_id:
            return vision_players

        smoothed_players: List[dict] = []
        for player in vision_players:
            seat_id = str(player.get("seat_id") or player.get("name") or "")
            updated_player = dict(player)
            updated_player["is_hero"] = seat_id == stable_hero_seat_id
            smoothed_players.append(updated_player)
        return smoothed_players

    async def update_from_vision(self, vision_state: dict):
        smoothed_players = self._smooth_hero_flags(list(vision_state.get("players", [])))
        self.spot_id = str(vision_state.get("spot_id", self.spot_id or ""))
        new_ocr_pot = vision_state.get("pot", 0.0)
        raw_board = vision_state.get("board", [])
        hero_cards = list(vision_state.get("hero_cards", []))
        incoming_street = str(vision_state.get("street", self.state) or self.state)
        incoming_legal_actions = list(vision_state.get("legal_actions", []))
        incoming_action_buttons = list(vision_state.get("action_buttons", []))
        incoming_state_confidence = float(vision_state.get("state_confidence", self.state_confidence or 0.0))

        if self._should_reuse_previous_legal_actions(
            incoming_street,
            list(raw_board),
            hero_cards,
            incoming_legal_actions,
            incoming_action_buttons,
        ):
            self.legal_actions = list(self.legal_actions)
            self.action_buttons = list(self.action_buttons)
        else:
            self.legal_actions = incoming_legal_actions
            self.action_buttons = incoming_action_buttons

        self.state_confidence = self._smooth_state_confidence(
            incoming_state_confidence,
            incoming_street,
            list(raw_board),
            hero_cards,
        )
        self._recent_state_confidences.append(self.state_confidence)
        self.hero_cards = hero_cards
        hero_seat_id = next((str(player.get("seat_id") or player.get("name") or "") for player in smoothed_players if player.get("is_hero")), "")
        if hero_seat_id:
            self._recent_hero_seat_ids.append(hero_seat_id)

        board_stage_hint = self._resolve_board_stage_hint(raw_board)
        validation_stage = self.state
        if board_stage_hint and self._STREET_ORDER[board_stage_hint] > self._STREET_ORDER[self.state]:
            validation_stage = board_stage_hint
        elif incoming_street in TableTracker.states:
            validation_stage = incoming_street

        # 1. Filtre anti-animations (Sanity Checker)
        new_board = self.sanity.validate_board_cards(validation_stage, raw_board)
        hand_is_observable = self.state != 'IDLE' or len(hero_cards) == 2 or len(new_board) > 0
        same_hand_board_transition = self.sanity.is_same_hand_board_transition(self.current_board, new_board)

        target_street = self._resolve_confirmed_target_street(incoming_street, board_stage_hint, new_board)
        street_advanced_this_frame = target_street != self.state

        if street_advanced_this_frame:
            self._advance_to_street(target_street)

        previous_pot = self.pot_total

        # 2. Détection de Nouvelle Main (chute du board ou du pot verifiee sur plusieurs frames)
        board_reset_candidate = self.sanity.is_possible_board_reset(self.current_board, new_board)
        ignored_board_reset_during_transition = board_reset_candidate and same_hand_board_transition
        if ignored_board_reset_during_transition:
            board_reset_candidate = False
        if board_reset_candidate:
            if self.pending_board_reset == new_board:
                self.pending_board_reset_frames += 1
            else:
                self.pending_board_reset = list(new_board)
                self.pending_board_reset_frames = 1

            if self.pending_board_reset_frames >= 2:
                await self._save_hand_history()
                self.reset_for_new_hand()
                return # On attend la prochaine frame pour lire les données propres
        else:
            self.pending_board_reset = None
            self.pending_board_reset_frames = 0

        pot_reset_candidate = self.sanity.is_possible_new_hand_pot(previous_pot, new_ocr_pot)
        ignored_pot_reset_during_transition = pot_reset_candidate and (
            self.pending_street_promotion is not None
            or same_hand_board_transition
            or street_advanced_this_frame
        )
        if ignored_pot_reset_during_transition:
            pot_reset_candidate = False
        if pot_reset_candidate:
            if self.pending_new_hand_pot == new_ocr_pot:
                self.pending_new_hand_frames += 1
            else:
                self.pending_new_hand_pot = new_ocr_pot
                self.pending_new_hand_frames = 1

            if self.pending_new_hand_frames >= 2:
                await self._save_hand_history()
                self.reset_for_new_hand()
                return # On attend la prochaine frame pour lire les données propres
        else:
            self.pending_new_hand_pot = None
            self.pending_new_hand_frames = 0

        total_bets_this_frame = 0.0

        # 3. Traitement des actions des joueurs avec Sanity Check
        for v_player in smoothed_players:
            seat_id = str(v_player.get("seat_id") or v_player.get("name") or f"seat_{len(self.players)}")
            seat_index = self._parse_seat_index(v_player)
            name = str(v_player.get("name") or seat_id)
            ocr_stack = float(v_player.get("stack", 0.0) or 0.0)
            is_active = bool(v_player.get("active", True))
            has_folded = bool(v_player.get("folded", False))
            is_hero = bool(v_player.get("is_hero", False))
            has_button = bool(v_player.get("has_button", False))
            
            if seat_id not in self.players:
                self.players[seat_id] = PlayerState(
                    seat_id=seat_id,
                    seat_index=seat_index if seat_index is not None else -1,
                    name=name,
                    starting_stack=ocr_stack,
                    current_stack=ocr_stack,
                    is_hero=is_hero,
                    has_button=has_button,
                )
                if hand_is_observable and seat_id not in self.observed_players_this_hand:
                    self.observed_players_this_hand.add(seat_id)
                    await self.db.record_observed_hand(name, self.state)
                logger.info(f"Nouveau joueur: {name} ({ocr_stack})")
                continue

            p = self.players[seat_id]
            was_active = p.is_active
            p.name = name
            if seat_index is not None:
                p.seat_index = seat_index
            p.is_hero = is_hero
            p.has_button = has_button

            if hand_is_observable and seat_id not in self.observed_players_this_hand:
                self.observed_players_this_hand.add(seat_id)
                await self.db.record_observed_hand(name, self.state)
            
            # Détection de Fold
            if was_active and (has_folded or not is_active):
                p.is_active = False
                p.has_folded = True
                await self._record_action(name, "FOLD", 0)
                continue

            p.is_active = is_active
            p.has_folded = has_folded

            # Validation du stack lu par l'OCR
            clean_stack = self.sanity.validate_stack_read(p.starting_stack, ocr_stack, p.bet)
            
            # Détection de Mise
            if p.is_active and clean_stack < p.current_stack:
                amount_invested = p.current_stack - clean_stack
                p.current_stack = clean_stack
                p.bet += amount_invested
                total_bets_this_frame += amount_invested
                
                action_type = "RAISE/BET" if amount_invested > self.pot_total * 0.1 else "CALL"
                await self._record_action(name, action_type, amount_invested)

        # 4. Validation Mathématique du Pot
        verified_pot = self.sanity.validate_pot_evolution(previous_pot, new_ocr_pot, total_bets_this_frame)
        if ignored_pot_reset_during_transition:
            verified_pot = previous_pot
        elif pot_reset_candidate and self.pending_new_hand_frames == 1:
            verified_pot = previous_pot
        self.last_pot = previous_pot
        self.pot_total = verified_pot

        # Mise à jour des positions
        self._calculate_positions()

        # 5. Gestion stricte de la State Machine (Street par Street)
        if len(new_board) == 3 and self.state == 'PREFLOP':
            self.deal_flop()
            logger.info(f"🃏 FLOP Détecté: {new_board}. Nouvel état: {self.state}")
            self.current_board = new_board
            
        elif (
            len(new_board) == 4 and self.state == 'FLOP'
            and self.pending_street_promotion != 'TURN'
        ):
            self.deal_turn()
            logger.info(f"🃏 TURN Détectée: {new_board}. Nouvel état: {self.state}")
            self.current_board = new_board
            
        elif (
            len(new_board) == 5 and self.state == 'TURN'
            and self.pending_street_promotion != 'RIVER'
        ):
            self.deal_river()
            logger.info(f"🃏 RIVER Détectée: {new_board}. Nouvel état: {self.state}")
            self.current_board = new_board
            
        # Si le bot a ses cartes en main et qu'on était inactifs
        elif len(hero_cards) == 2 and self.state == 'IDLE':
            self.deal_hole_cards()
            logger.info(f"🃏 Cartes en main. Nouvel état: {self.state}")

        if not board_reset_candidate and not ignored_board_reset_during_transition and len(new_board) in (0, 3, 4, 5):
            self.current_board = new_board

    def get_primary_villain(self) -> Optional[PlayerState]:
        active_villains = [
            player for player in self.players.values()
            if not player.is_hero and player.is_active and not player.has_folded
        ]
        if not active_villains:
            return None
        return min(active_villains, key=lambda player: player.current_stack)

    def get_effective_stack(self) -> float:
        """
        Calcule le tapis effectif.
        En Multiway (plus de 2 joueurs), le tapis effectif est le plus gros tapis parmi tous
        les adversaires restants que le Hero peut couvrir, limitant ainsi l'exposition totale du Hero.
        """
        hero = next((player for player in self.players.values() if player.is_hero), None)
        active_villains = [
            player for player in self.players.values()
            if not player.is_hero and player.is_active and not player.has_folded
        ]
        
        if not hero:
            return 0.0
            
        if not active_villains:
            return max(0.0, hero.current_stack)
            
        # Le max des stacks des adversaires, limité par notre propre stack
        max_villain_stack = max(v.current_stack for v in active_villains)
        return max(0.0, min(hero.current_stack, max_villain_stack))

    def _calculate_positions(self):
        """
        Calcule la position de chaque joueur actif par rapport au Bouton Dealer.
        6-Max Positions: SB, BB, UTG, HJ, CO, BTN
        """
        active_players = [p for p in self.players.values() if p.is_active and not p.has_folded]
        if not active_players:
            return
            
        # Tri des joueurs par seat_index (dans le sens des aiguilles d'une montre)
        sorted_players = sorted(active_players, key=lambda p: p.seat_index)
        
        # Trouver l'index du bouton
        button_idx = -1
        for i, p in enumerate(sorted_players):
            if p.has_button:
                button_idx = i
                break
                
        # S'il n'y a pas de bouton clair, on ne calcule pas
        if button_idx == -1:
            return
            
        # Réorganiser la liste pour commencer par la Small Blind (le joueur APRÈS le bouton)
        ordered_from_sb = sorted_players[button_idx+1:] + sorted_players[:button_idx+1]
        
        num_players = len(ordered_from_sb)
        
        if num_players == 2:
            # Heads-Up: Le bouton est la SB
            ordered_from_sb[0].position = "BB"
            ordered_from_sb[1].position = "BTN"
        elif num_players == 3:
            ordered_from_sb[0].position = "SB"
            ordered_from_sb[1].position = "BB"
            ordered_from_sb[2].position = "BTN"
        elif num_players == 4:
            ordered_from_sb[0].position = "SB"
            ordered_from_sb[1].position = "BB"
            ordered_from_sb[2].position = "CO"
            ordered_from_sb[3].position = "BTN"
        elif num_players == 5:
            ordered_from_sb[0].position = "SB"
            ordered_from_sb[1].position = "BB"
            ordered_from_sb[2].position = "HJ"
            ordered_from_sb[3].position = "CO"
            ordered_from_sb[4].position = "BTN"
        elif num_players >= 6:
            ordered_from_sb[0].position = "SB"
            ordered_from_sb[1].position = "BB"
            ordered_from_sb[2].position = "UTG"
            
            # Gestion des places entre UTG et HJ si table pleine
            for i in range(3, num_players - 3):
                ordered_from_sb[i].position = f"EP{i-2}" # Early Position
                
            ordered_from_sb[-3].position = "HJ"
            ordered_from_sb[-2].position = "CO"
            ordered_from_sb[-1].position = "BTN"

    async def _record_action(self, player_name: str, action: str, amount: float):
        action_data = {
            "player": player_name,
            "action": action,
            "amount": amount,
            "pot_size": self.pot_total,
            "street": self.state
        }
        self.current_hand_actions.append(action_data)
        logger.info(f"Action détectée -> {player_name}: {action} ({amount})")
        await self.db.update_player_action(player_name, action_data)

    async def _save_hand_history(self):
        if not self.current_hand_actions:
            return
        logger.info("Sauvegarde de l'historique de la main en base de données.")
        await self.db.insert_hand_history("Table_1", self.current_board, self.current_hand_actions)
