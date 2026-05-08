import re

with open("src/bot/sanity_checker.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix max pot allowed
content = content.replace("self.max_pot_allowed = 2000.0", "self.max_pot_allowed = 200000.0")

# 2. Fix fuzzy action matching
old_action_logic = """        if legal_actions and action_intent.action not in legal_actions:
            reasons.append(GateReason(
                code="ILLEGAL_ACTION",
                message="L'action demandee n'appartient pas aux actions autorisees.",
                context={"action": action_intent.action, "legal_actions": legal_actions}
            ))"""

new_action_logic = """        if legal_actions:
            base_actions = {
                "RAISE_HALF": "RAISE",
                "RAISE_POT": "RAISE",
                "BET": "BET",
                "ALL_IN": "ALL_IN",
                "CALL": "CALL",
                "CHECK": "CHECK",
                "FOLD": "FOLD",
                "RAISE": "RAISE",
            }
            action_base = base_actions.get(action_intent.action, action_intent.action)
            is_legal = any(action_base in legal for legal in legal_actions) or action_intent.action in legal_actions
            if not is_legal:
                reasons.append(GateReason(
                    code="ILLEGAL_ACTION",
                    message="L'action demandee n'appartient pas aux actions autorisees.",
                    context={"action": action_intent.action, "legal_actions": legal_actions}
                ))"""
content = content.replace(old_action_logic, new_action_logic)


# 3. Fix deflation protection
deflation_code = """        if new_ocr_pot > expected_pot:
            # HALLUCINATION OCR DÉTECTÉE !
            logger.warning(f"⚠️ Anomalie OCR bloquée ! Pot lu: {new_ocr_pot} | Pot mathématique attendu: {expected_pot}. Correction automatique appliquée.")
            # On force la valeur mathématique pour sauver la main
            return expected_pot

        # NEW CODE: Anti-deflation
        if expected_pot > 0 and new_ocr_pot < expected_pot and (new_ocr_pot / expected_pot) < 0.5:
            logger.warning(f"⚠️ Anomalie OCR bloquée ! Pot lu ({new_ocr_pot}) trop bas par rapport au pot mathématique ({expected_pot}).")
            return expected_pot"""

content = content.replace("""        if new_ocr_pot > expected_pot:
            # HALLUCINATION OCR DÉTECTÉE !
            logger.warning(f"⚠️ Anomalie OCR bloquée ! Pot lu: {new_ocr_pot} | Pot mathématique attendu: {expected_pot}. Correction automatique appliquée.")
            # On force la valeur mathématique pour sauver la main
            return expected_pot""", deflation_code)

# 4. Fix validate stack drop hardcoded limits
stack_drop_old = "if (drop_ratio < 0.15 and amount_dropped > 5.0) or (0 < amount_dropped < 0.02):"
stack_drop_new = "if (drop_ratio < 0.15 and amount_dropped > max(5.0, (current_stack + amount_dropped) * 0.05)) or (0 < amount_dropped < 0.02):"
content = content.replace(stack_drop_old, stack_drop_new)

with open("src/bot/sanity_checker.py", "w", encoding="utf-8") as f:
    f.write(content)
