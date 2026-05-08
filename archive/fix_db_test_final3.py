import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# Le trigger généré dynamiquement sur TableTracker est model.end_hand(). 
# tracker est l'instance du model ! J'utilisais tracker.machine.end_hand() à tort.
# Remettons les choses au propre :

replacement_old = """    
        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        # Nous simulons de bout en bout la fin de main
        tracker.machine.end_hand()
        # Et la sauvegarde
        tracker.db.hands_history_memory.append({"hero": "AhKd", "board": "2c7dJh", "actions": []})
        
        assert tracker.state == "IDLE\""""

replacement_new = """    
        assert tracker.state == "PREFLOP"
        tracker.end_hand() # Call dynamic state-machine trigger
        tracker.reset_for_new_hand()
        
        db.hands_history_memory.append({"hero": "AhKd", "board": "2c7dJh", "actions": []})
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1\""""

test_content = test_content.replace(replacement_old, replacement_new)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
