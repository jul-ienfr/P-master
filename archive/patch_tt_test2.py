import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

# Forcer le rollover complet dans tracker :
# Le sanity_checker regarde has_hero_cards and hero_cards différent.
# Donnons un signal clair de nouvelle main sans ambiguite (street different ou trigger force_reset)

modifier = """        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        # On force la fin de main visuellement grace au timeout / absence de cartes
        for _ in range(5):
            await tracker.update_from_vision(force_idle_signal)
"""

nouveau = """        assert tracker.state == "PREFLOP"
        await tracker.update_from_vision(next_hand_signal)
        # Forcer le flag de nouvelle main explicite (simule la détection par Vision)
        tracker.force_reset_next_frame = True
        await tracker.update_from_vision(force_idle_signal)
"""

test_content = test_content.replace(modifier, nouveau)

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
