# -*- coding: utf-8 -*-
import sys

with open('src/vision/detector.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        yolo_state = self._run_yolo_detection(frame, conf_threshold)
        if self._has_meaningful_signal(yolo_state):
            yolo_state.metadata["table_detected"] = True
            return yolo_state'''

new_code = '''        yolo_state = self._run_yolo_detection(frame, conf_threshold)
        if self._has_meaningful_signal(yolo_state):
            yolo_state.metadata["table_detected"] = True
            
            # --- HYBRID REASONING: YOLO + TEMPLATE FALLBACK ---
            # Si le nouveau modele YOLO hesite sur les cartes, on comble les trous avec l'ancien systeme de templates
            if not yolo_state.hero_cards and self.fallback_detector.available():
                fallback_state = self._run_template_fallback(frame)
                yolo_state.hero_cards = fallback_state.hero_cards
                # On tente aussi de recuperer le board si yolo ne le voit pas
                if not yolo_state.board_cards:
                    yolo_state.board_cards = fallback_state.board_cards
                    
            return yolo_state'''

content = content.replace(old_code, new_code)

with open('src/vision/detector.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied for Hybrid YOLO+Template fusion")
