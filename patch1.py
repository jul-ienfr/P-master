import sys

with open('src/bot/decision_maker.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update signature
content = content.replace(
    '        hero_position: str,\n        action_history: Optional[List[Dict[str, Any]]],\n    ) -> tuple[str, dict]:',
    '        hero_position: str,\n        action_history: Optional[List[Dict[str, Any]]],\n        effective_stack: float = 0.0,\n        pot: float = 0.0,\n    ) -> tuple[str, dict]:'
)

# 2. Update logic
old_logic = '''        chosen_action = "CHECK" if "CHECK" in legal_actions else "FOLD"
        if in_range:
            if facing_raise:
                if aggressive_action and _combo_in_range(hero_combo, PREFLOP_FAST_3BET_RANGE):
                    chosen_action = aggressive_action
                elif "CALL" in legal_actions:
                    chosen_action = "CALL"
                elif "CHECK" in legal_actions:
                    chosen_action = "CHECK"'''

new_logic = '''        chosen_action = "CHECK" if "CHECK" in legal_actions else "FOLD"
        dynamic_amount = None

        if in_range:
            if facing_raise:
                if aggressive_action and _combo_in_range(hero_combo, PREFLOP_FAST_3BET_RANGE):
                    chosen_action = aggressive_action
                    dynamic_amount = pot * 3.2 if normalized_hero_position in ["SB", "BB"] else pot * 2.8
                elif "CALL" in legal_actions:
                    chosen_action = "CALL"
                elif "CHECK" in legal_actions:
                    chosen_action = "CHECK"'''
content = content.replace(old_logic, new_logic)

old_logic2 = '''            else:
                if aggressive_action:
                    chosen_action = aggressive_action
                elif "CHECK" in legal_actions:'''

new_logic2 = '''            else:
                if aggressive_action:
                    chosen_action = aggressive_action
                    if effective_stack > pot * 50:
                        dynamic_amount = pot * 1.5
                    elif effective_stack < pot * 15 and effective_stack > 0:
                        dynamic_amount = effective_stack
                    else:
                        dynamic_amount = pot * 1.8
                elif "CHECK" in legal_actions:'''
content = content.replace(old_logic2, new_logic2)

# 3. Update dictionary
content = content.replace(
    '            "decision_confidence": confidence,\n            "actions"',
    '            "decision_confidence": confidence,\n            "dynamic_amount": dynamic_amount,\n            "actions"'
)

# 4. Update caller
old_caller = '''            gto_action, gto_details = self._run_preflop_fast_path(
                hero_hand=hero_hand,
                legal_actions=legal_actions,
                hero_position=hero_position,
                action_history=action_history,
            )'''

new_caller = '''            gto_action, gto_details = self._run_preflop_fast_path(
                hero_hand=hero_hand,
                legal_actions=legal_actions,
                hero_position=hero_position,
                action_history=action_history,
                effective_stack=effective_stack,
                pot=pot,
            )'''
content = content.replace(old_caller, new_caller)

with open('src/bot/decision_maker.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied to decision_maker.py")
