import re

with open("src/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Mise à jour de _read_action_button_text
keyword_block_old = r"""        keyword_tokens = \(
            "check",
            "call",
            "fold",
            "bet",
            "raise",
            "miser",
            "suivre",
            "passer",
            "payer",
            "relancer",
            "reprendre",
            "jouer",
            "resume",
            "back",
            "vite",
        \)"""

keyword_block_new = """        keyword_tokens = (
            "check",
            "call",
            "fold",
            "bet",
            "raise",
            "miser",
            "suivre",
            "passer",
            "payer",
            "relancer",
            "reprendre",
            "jouer",
            "resume",
            "back",
            "vite",
            "time",
            "temps",
            "bank",
            "banque",
            "more",
            "give",
        )"""
content = re.sub(keyword_block_old, keyword_block_new, content)

# 2. Mise à jour de _classify_action_button_label
classify_old = r"""            if any\(token in normalized_text for token in \("reprendre", "jouer", "resume", "continuer"\)\):
                return "resume_hand" """

classify_new = """            if any(token in normalized_text for token in ("time", "temps", "bank", "banque")):
                return "time_bank_button"
            if any(token in normalized_text for token in ("reprendre", "jouer", "resume", "continuer")):
                return "resume_hand" """
content = re.sub(classify_old, classify_new, content)

# 3. Injection dans _classify_slot_button_label
slot_old = r"""        if slot_key == "CALL":"""
slot_new = """        if any(token in normalized_text for token in ("time", "temps", "bank", "banque")):
            return "time_bank_button"
            
        if slot_key == "CALL":"""
content = content.replace(slot_old, slot_new)

# 4. Injection prioritaire dans le main_loop
loop_old = r"""                    detector_started_at = time.monotonic\(\)
                    state = await self\._process_frame\(frame\)
                    detector_ms = \(time\.monotonic\(\) - detector_started_at\) \* 1000\.0
                    self\._set_loop_stage\("convert_state", publish=True\)"""

loop_new = """                    detector_started_at = time.monotonic()
                    state = await self._process_frame(frame)
                    
                    # --- INTERCEPTION JIT: TIME BANK ---
                    time_bank_btn = next((b for b in state.action_buttons if b.class_name == "time_bank_button"), None)
                    if time_bank_btn:
                        logger.warning("TIME BANK ONSCREEN -> Clic auto sécurité pour acheter du temps.")
                        await self.action_controller.click_at(*(int(c) for c in time_bank_btn.center))
                        await asyncio.sleep(0.5)
                        continue
                    # ------------------------------------
                    
                    detector_ms = (time.monotonic() - detector_started_at) * 1000.0
                    self._set_loop_stage("convert_state", publish=True)"""
content = re.sub(loop_old, loop_new, content)

with open("src/main.py", "w", encoding="utf-8") as f:
    f.write(content)

