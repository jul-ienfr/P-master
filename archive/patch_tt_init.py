import re

with open('src/bot/table_tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Ajout des variablies pour Pot Catch-up 
# et Temporal Buffer pour les cartes
init_old = """        # Règles de passage (impossible de passer de PREFLOP à RIVER)"""
init_new = """        # --- IMPROVED RELIABILITY BUFFERS ---
        self._consecutive_ocr_pot_spikes = 0
        self._last_spiked_ocr_pot = 0.0
        
        self._temporal_board_buffer = []
        self._missing_board_frames = 0
        # ------------------------------------
        
        # Règles de passage (impossible de passer de PREFLOP à RIVER)"""

content = content.replace(init_old, init_new)

with open('src/bot/table_tracker.py', 'w', encoding='utf-8') as f:
    f.write(content)
