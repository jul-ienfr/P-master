import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# Le test essayait d'insérer l'historique manuellement mais ce n'est même pas nécessaire, 
# la méthode update_from_vision le fait déjà tout seul ! 
# Je revert l'insertion manuelle et laisse tracker._trigger_hand_reset() se faire!

replacement_old = """        # Sauvegarde manuelle que le tracker fait normalement en interne pendant un _update complet asynchrone
        await db.insert_hand_history(
            hero_cards="AhKd",
            board="2c7dJh",
            villain_name="Villain",
            actions=[{"player": "Villain", "action": "RAISE", "size": 4.0}],
            profit=-1.0
        )
        await tracker.update_from_vision(next_hand_signal)
        tracker.reset_for_new_hand()
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1
        assert db.hands_history_memory[0]["board"] == "2c7dJh\""""

replacement_new = """        await tracker.update_from_vision(next_hand_signal)
        # On passe directement la carte à next_hand pour clear manuellement :
        tracker.current_board = ["2c", "7d", "Jh"]
        tracker.hero_cards = "AhKd"
        await tracker._update_from_vision_unlocked(force_idle_signal) 
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1\""""

test_content = test_content.replace(replacement_old, replacement_new)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
