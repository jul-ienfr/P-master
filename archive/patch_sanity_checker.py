import re

with open('src/bot/sanity_checker.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 3. Dynamic OCR Error Margins
new_validate_pot = """    @staticmethod
    def validate_pot_evolution(expected_pot: float, ocr_pot: float, is_new_hand: bool, state_confidence: float = 1.0) -> float:
        if is_new_hand:
            if ocr_pot > 0.0 and ocr_pot < 20.0:
                return ocr_pot
            return expected_pot

        # Dynamic Margin Override
        if state_confidence >= 0.95:
            # Très haute confiance OCR : on augmente la marge de tolérance (jusqu'à 25%)
            margin_of_error = max(expected_pot * 0.25, 4.0)
            if abs(expected_pot - ocr_pot) <= margin_of_error:
                return ocr_pot
                
        margin_of_error = max(expected_pot * 0.05, 2.0)
        
        if ocr_pot < expected_pot - margin_of_error:
            logger.warning(f"Un pot OCR trop bas est souvent un retard de lecture (Math: {expected_pot}, OCR: {ocr_pot}). On garde {expected_pot}")
            return expected_pot
            
        if ocr_pot > expected_pot + margin_of_error:
            logger.warning(f"HALLUCINATION OCR DÉTECTÉE ! Pot OCR énorme {ocr_pot} vs Pot mathématique {expected_pot}. Fallback au mathématique.")
            return expected_pot

        return ocr_pot"""

content = re.sub(r'    @staticmethod\s+def validate_pot_evolution\(expected_pot: float, ocr_pot: float, is_new_hand: bool\) -> float:.*?return ocr_pot', new_validate_pot, content, flags=re.DOTALL)

# On met a jour la signature d'appel dans le table tracker après
with open('src/bot/sanity_checker.py', 'w', encoding='utf-8') as f:
    f.write(content)
