import sys

with open('src/bot/decision_maker.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        # Geometric Sizing + SPR Optimization
        bet_size = _bet_size_from_action(gto_details.get("chosen_action", final_action), pot, effective_stack, board)'''

new_code = '''        # Geometric Sizing + SPR Optimization
        bet_size = gto_details.get("dynamic_amount")
        if bet_size is None:
            bet_size = _bet_size_from_action(gto_details.get("chosen_action", final_action), pot, effective_stack, board)'''

content = content.replace(old_code, new_code)

with open('src/bot/decision_maker.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied for bet_size")
