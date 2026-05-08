# -*- coding: utf-8 -*-
import sys

with open('src/vision/temporal_ocr.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''    def read_stable_amount(self, image_crop: np.ndarray, tolerance: float = 0.05) -> Optional[float]:
        """
        Lit un montant et le lisse temporellement.
        tolérance: Différence acceptable (en %) pour considérer que deux lectures sont "les mêmes".
        """
        raw_amount = self.ocr_engine.read_and_parse_amount(image_crop)
        
        if raw_amount is None:'''

new_code = '''    def read_stable_amount(self, image_crop: np.ndarray, tolerance: float = 0.05, chip_count: Optional[int] = None) -> Optional[float]:
        """
        Lit un montant et le lisse temporellement.
        tolérance: Différence acceptable (en %) pour considérer que deux lectures sont "les mêmes".
        chip_count: Nombre de piles de jetons (YOLO) détectées dans la même zone (Sanity Check visuel).
        """
        raw_amount = self.ocr_engine.read_and_parse_amount(image_crop)
        
        # --- Sanity Check YOLO vs OCR ---
        if raw_amount is not None and chip_count is not None:
            if chip_count == 0 and raw_amount > 0.0:
                logger.warning(f"Sanity Check Echoue: L'OCR lit {raw_amount} mais YOLO ne voit AUCUN jeton (chip_count=0).")
        
        if raw_amount is None:'''

content = content.replace(old_code, new_code)

with open('src/vision/temporal_ocr.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied for temporal_ocr.py")
