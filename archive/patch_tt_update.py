import re

with open('src/bot/table_tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()


# UPDATE validate_pot_evolution in TableTracker call:
content = re.sub(
    r'verified_pot = self\.sanity\.validate_pot_evolution\(previous_pot \+ total_bets_this_frame, normalized_new_ocr_pot, self\.is_distinct_board_rollover\)',
    r'verified_pot = self.sanity.validate_pot_evolution(previous_pot + total_bets_this_frame, normalized_new_ocr_pot, self.is_distinct_board_rollover, state_confidence)',
    content
)

# POT CATCHUP: Insert catch-up logic right after verified_pot = ...
# Search for the block starting with: verified_pot = self.sanity.validate_pot_evolution... 

pot_catchup_code = """
        # --- POT CATCH-UP MECHANISM (RELIABILITY UPDATE) ---
        if not self.is_distinct_board_rollover and total_bets_this_frame == 0.0:
            if normalized_new_ocr_pot > verified_pot and normalized_new_ocr_pot == self._last_spiked_ocr_pot:
                self._consecutive_ocr_pot_spikes += 1
                if self._consecutive_ocr_pot_spikes >= 3:
                    missing_diff = normalized_new_ocr_pot - verified_pot
                    logger.warning(f"POT CATCH-UP DÉCLENCHÉ ! Pot OCR ({normalized_new_ocr_pot}) est plus haut que le calcul ({verified_pot}) depuis 3 frames sans bet détecté. Assignation d'un bet fantôme de {missing_diff}")
                    self.current_pot = normalized_new_ocr_pot
                    # Résolution de la variable catchup pour que le solver ait le bon compte
                    verified_pot = normalized_new_ocr_pot
                    self._consecutive_ocr_pot_spikes = 0
            elif normalized_new_ocr_pot > verified_pot:
                self._last_spiked_ocr_pot = normalized_new_ocr_pot
                self._consecutive_ocr_pot_spikes = 1
            else:
                self._consecutive_ocr_pot_spikes = 0
                self._last_spiked_ocr_pot = 0.0
        else:
            self._consecutive_ocr_pot_spikes = 0
            self._last_spiked_ocr_pot = 0.0
        # ---------------------------------------------------
"""

content = content.replace(
    """verified_pot = self.sanity.validate_pot_evolution(previous_pot + total_bets_this_frame, normalized_new_ocr_pot, self.is_distinct_board_rollover, state_confidence)""",
    """verified_pot = self.sanity.validate_pot_evolution(previous_pot + total_bets_this_frame, normalized_new_ocr_pot, self.is_distinct_board_rollover, state_confidence)""" + pot_catchup_code
)

# Replace new_board processing with Temporal Board Buffer
board_logic_old = """        if self.is_distinct_board_rollover:
            self.current_board = new_board
        elif len(new_board) >= len(self.current_board):
            self.current_board = new_board"""

board_logic_new = """        # --- TEMPORAL BOARD BUFFER (RELIABILITY UPDATE) ---
        if self.is_distinct_board_rollover:
            self._temporal_board_buffer = new_board
            self.current_board = new_board
            self._missing_board_frames = 0
        elif len(new_board) >= len(self._temporal_board_buffer):
            # Si le board augmente ou reste identique
            self._temporal_board_buffer = new_board
            self.current_board = new_board
            self._missing_board_frames = 0
        elif len(new_board) < len(self._temporal_board_buffer):
            # Une ou plusieurs cartes ont disparu soudainement (Flicker, Animation)
            self._missing_board_frames += 1
            if self._missing_board_frames <= 3:
                # On utilise le buffer (On garde les anciennes cartes)
                logger.info(f"TEMPORAL BUFFER: Maintien du board {self._temporal_board_buffer} malgré perte de cartes ({new_board}) Frame loss: {self._missing_board_frames}/3")
                self.current_board = self._temporal_board_buffer
            else:
                # Perte de cartes continue, on accepte le nouveau board shrinké
                self._temporal_board_buffer = new_board
                self.current_board = new_board
        # ----------------------------------------------------"""

content = content.replace(board_logic_old, board_logic_new)

# Board reset
board_reset_old = """    def reset_for_new_hand(self):
        logger.info(f"--- Nouvelle Main Détectée (État: {self.state}) ---")"""
board_reset_new = """    def reset_for_new_hand(self):
        logger.info(f"--- Nouvelle Main Détectée (État: {self.state}) ---")
        self._temporal_board_buffer = []
        self._missing_board_frames = 0
        self._consecutive_ocr_pot_spikes = 0
        self._last_spiked_ocr_pot = 0.0"""
content = content.replace(board_reset_old, board_reset_new)

with open('src/bot/table_tracker.py', 'w', encoding='utf-8') as f:
    f.write(content)
