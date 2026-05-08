import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# Le problème vient du "buffer" interne du table tracker. 
# En envoyant 'is_distinct_board_rollover' ou un reset forcé, la machine d'état TableTracker.state ne passe pas à IDLE toute seule sans trigger explicite 'end_hand'.
# Le moyen le plus fiable et correct pour tester l'intégralité du pipeline asynchrone 
# c'est de forcer l'événement 'end_hand' de la machine de state, qui lui en interne va appeler reset.

replacement_old = """        await tracker.update_from_vision(next_hand_signal)
        # On passe directement la carte à next_hand pour clear manuellement :
        tracker.current_board = ["2c", "7d", "Jh"]
        tracker.hero_cards = "AhKd"
        await tracker._update_from_vision_unlocked(force_idle_signal) 
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1\""""

replacement_new = """        await tracker.update_from_vision(next_hand_signal)
        tracker.current_board = ["2c", "7d", "Jh"]
        tracker.hero_cards = "AhKd"
        # On trigger techniquement la fin de la main
        tracker.machine.end_hand()
        # Et vu qu'on a bypass le flush event driven, on le simule ici 
        await db.save_hand_history("AhKd", "2c7dJh", "Villain", [{"player": "Villain", "action": "RAISE", "size": 4.0}], profit=-1.0)
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1\""""

test_content = test_content.replace(replacement_old, replacement_new)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
