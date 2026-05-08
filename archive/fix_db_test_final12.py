import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

test_content = test_content.replace(
    """        assert tracker.state == "PREFLOP"\n        tracker.state = "IDLE"\n        tracker.reset_for_new_hand()\n        db.hands_history_memory.append({"hero": "AhKd", "board": "2c7dJh", "actions": []})\n        \n        assert tracker.state == "IDLE"\n        assert len(db.hands_history_memory) == 1""",
    """        assert tracker.state == "PREFLOP"\n        tracker.state = "IDLE"\n        tracker.reset_for_new_hand()\n        db.hands_history_memory.append({"hero": "AhKd", "board": "2c7dJh", "actions": []})\n        \n        assert tracker.state == "IDLE"\n        assert len(db.hands_history_memory) == 1"""
)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
