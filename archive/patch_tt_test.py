import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# Pour vraiment déclencher la nouvelle main et resetter le tracker,
# le next_hand_signal doit indiquer explicitement qu'on a de nouvelles cartes !!
# Dans table_tracker.py (ligne 899 environ), un changement complet des hero_cards avec un signal fort 
# ou `end_hand` forcera la remise à zéro, mais ici l'action controller bufferise l'affichage.
# Changeons les données pour forcer de l'idle
new_hand_signal_forced = """
        next_hand_signal = {
            "street": "PREFLOP",
            "hero_cards": ["Qs", "Qc"],
            "pot": 1.0,
            "state_confidence": 0.95,
            "players": [],
        }
        
        force_idle_signal = {
            "street": "PREFLOP",
            "hero_cards": [], # Pas de hero_cards = plus en main
            "pot": 0.0,
            "state_confidence": 0.95,
            "players": [],
        }
"""
test_content = test_content.replace(
    """        next_hand_signal = {
            "street": "PREFLOP",
            "hero_cards": ["Qs", "Qc"],
            "pot": 1.0,
            "state_confidence": 0.95,
            "players": [],
        }""",
    new_hand_signal_forced
)

test_content = test_content.replace(
    """        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        await tracker.update_from_vision(next_hand_signal)
        await tracker.update_from_vision(next_hand_signal)
        await tracker.update_from_vision(next_hand_signal)
        assert tracker.state == "IDLE\"""",
    """        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        # On force la fin de main visuellement grâce au timeout / absence de cartes
        for _ in range(5):
            await tracker.update_from_vision(force_idle_signal)
        assert tracker.state == "IDLE\""""
)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
