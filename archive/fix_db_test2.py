import re

with open('tests/test_local_smoke_integration.py', 'r', encoding='utf-8') as f:
    test_content = f.read()

test_content = test_content.replace('db.save_hand_history', 'db.insert_hand_history')

with open('tests/test_local_smoke_integration.py', 'w', encoding='utf-8') as f:
    f.write(test_content)
