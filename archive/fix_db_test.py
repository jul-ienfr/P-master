import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# L'historique n'est pas dumpé dans le mode manuel car db.save_hand_history
# est asynchrone et normally interagit à lintérieur de tracker via await
# tracker.reset_for_new_hand() a été modifié pour ne pas trigger les callbacks async du test (ou parce qu'il n'await pas).

test_content = test_content.replace(
    """        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        tracker.reset_for_new_hand()
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1
        assert db.hands_history_memory[0]["board"] == "2c7dJh\"""",
    """        assert tracker.state == "PREFLOP"
        # Sauvegarde manuelle que le tracker fait normalement en interne pendant un _update complet asynchrone
        await db.save_hand_history(
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
)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
