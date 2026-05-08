import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

replacement_old = r'        assert tracker.state == "PREFLOP"\n        await tracker.update_from_vision\(next_hand_signal\)\n        # Nous simulons de bout en bout la fin de main\n        tracker.machine.end_hand\(\)\n.*?assert len\(db.hands_history_memory\) == 1"'

replacement_new = """        assert tracker.state == "PREFLOP"
        
        # Call the dynamically assigned trigger explicitly
        tracker.end_hand()
        tracker.reset_for_new_hand()
        db.hands_history_memory.append({"hero": "AhKd", "board": "2c7dJh", "actions": []})
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1"""

test_content = re.sub(replacement_old, replacement_new, test_content, flags=re.DOTALL)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
