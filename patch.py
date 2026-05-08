import re

with open("c:/Users/julie/Desktop/Poker-master/src/bot/sanity_checker.py", "r") as f:
    content = f.read()

# 1. Fix validate_pot_evolution
content = re.sub(
    r"""        if new_ocr_pot > expected_pot:
            # HALLUCINATION OCR DÉTECTÉE !
            logger\.warning\(f"⚠️ Anomalie OCR bloquée ! Pot lu: \{new_ocr_pot\} \| Pot mathématique attendu: \{expected_pot\}\. Correction automatique appliquée\."\)
            # On force la valeur mathématique pour sauver la main
            return expected_pot

        # Un pot OCR trop bas est souvent un retard de lecture ou une mise partiellement observée\.
        # On conserve la valeur OCR pour éviter d'inventer des jetons et de déclencher des resets parasites\.
        return new_ocr_pot""",
    """        if new_ocr_pot > expected_pot:
            # HALLUCINATION OCR DÉTECTÉE !
            logger.warning(f"⚠️ Anomalie OCR bloquée ! Pot lu: {new_ocr_pot} | Pot mathématique attendu: {expected_pot}. Correction automatique appliquée.")
            # On force la valeur mathématique pour sauver la main
            return expected_pot

        if expected_pot > 0 and new_ocr_pot < expected_pot and (new_ocr_pot / expected_pot) < 0.5:
            logger.warning(f"⚠️ Anomalie OCR bloquée ! Pot lu ({new_ocr_pot}) trop bas par rapport au pot mathématique ({expected_pot}).")
            return expected_pot

        # Un pot OCR trop bas est souvent un retard de lecture ou une mise partiellement observée.
        # On conserve la valeur OCR pour éviter d'inventer des jetons et de déclencher des resets parasites.
        return new_ocr_pot""",
    content
)

# 2. Fix validate_stack_read
content = re.sub(
    r"""\(drop_ratio < 0\.15 and amount_dropped > 5\.0\)""",
    """(drop_ratio < 0.15 and amount_dropped > max(5.0, (current_stack + amount_dropped) * 0.05))""",
    content
)

# 3. & 4. Fix evaluate_action_gate
# - self.max_pot_allowed limit removal / change
content = re.sub(
    r"""        self\.max_pot_allowed = 2000\.0  # Sécurité hardcodée \(ex: NL100, pot max théorique\)""",
    """        self.max_pot_allowed = 200000.0  # Sécurité hardcodée (ex: NL100, pot max théorique)""",
    content
)

# - fuzzy matching for legal_actions
content = re.sub(
    r"""        if legal_actions and action_intent\.action not in legal_actions:
            reasons\.append\(GateReason\(
                code="ILLEGAL_ACTION",
                message="L'action demandee n'appartient pas aux actions autorisees\.",
                context=\{"action": action_intent\.action, "legal_actions": legal_actions\}
            \)\)""",
    """        if legal_actions:
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
            # Fuzzy match: is the base action part of any legal action?
            is_legal = any(action_base in legal for legal in legal_actions) or action_intent.action in legal_actions
            if not is_legal:
                reasons.append(GateReason(
                    code="ILLEGAL_ACTION",
                    message="L'action demandee n'appartient pas aux actions autorisees.",
                    context={"action": action_intent.action, "legal_actions": legal_actions}
                ))""",
    content
)

with open("c:/Users/julie/Desktop/Poker-master/src/bot/sanity_checker.py", "w") as f:
    f.write(content)
