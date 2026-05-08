import re

with open("src/bot/action_controller.py", "r", encoding="utf-8") as f:
    content = f.read()

# On cible précisément le bloc tel qu'il est défini actuellement
pattern = re.compile(
    r'(elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:.*?return \{"ok": False, "action": action_name, "reason": "missing_bet_box_coords"\})',
    re.DOTALL
)

match = pattern.search(content)

if match:
    old_block = match.group(1)
    
    new_block = """elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:
            text_box_coords = coords_mapping.get("BET_BOX")
            bet_btn_coords = coords_mapping.get("BET_BTN")

            if not text_box_coords or not bet_btn_coords:
                logger.error(f"CLICK_RESULT | action={action_name} status=skipped reason=missing_coords (BET_BOX or BET_BTN introuvable)")
                return {"ok": False, "action": action_name, "reason": "missing_coords"}

            amount_to_bet = str(action_intent.bet_size if action_intent.bet_size is not None else 5.50)

            async def _attempt_full_bet_sequence(attempt_idx: int) -> dict:
                # 1. Vérification JIT initiale (avant d'engager le double click)
                if jit_check is not None:
                    is_valid = await jit_check()
                    if not is_valid:
                        raise Exception("JIT Check Failed: La zone d'action a muté avant le clic focus sur la zone de texte (BET_BOX).")

                # Focus sur la zone de texte avec léger jitter
                box_jitter_x = random.randint(-4, 4) if attempt_idx > 0 else 0
                box_jitter_y = random.randint(-4, 4) if attempt_idx > 0 else 0
                
                clicked = await self.click_at(text_box_coords[0] + box_jitter_x, text_box_coords[1] + box_jitter_y, double_click=True)
                if not clicked:
                    logger.error("CLICK_RESULT | action=%s status=failed reason=bet_box_click_failed", action_name)
                    return {"ok": False, "action": action_name, "reason": "bet_box_click_failed"}

                # 2. Frappe du montant
                await self.send_text(amount_to_bet)
                
                # Petit délai humain de réflexion entre la saisie et la validation par clic
                await asyncio.sleep(random.uniform(0.12, 0.28))
                
                # 3. Vérification JIT imminente finale (juste avant de cliquer sur 'Miser')
                if jit_check is not None:
                    is_valid = await jit_check()
                    if not is_valid:
                        raise Exception("JIT Check Failed: La zone d'action a muté juste avant le clic final sur le bouton Bet.")

                btn_jitter_x = random.randint(-3, 3) if attempt_idx > 0 else 0
                btn_jitter_y = random.randint(-3, 3) if attempt_idx > 0 else 0
                
                clicked_btn = await self.click_at(bet_btn_coords[0] + btn_jitter_x, bet_btn_coords[1] + btn_jitter_y)
                if clicked_btn:
                    logger.info(f"-> Action exécutée : {action_name} ({amount_to_bet})")
                    return {
                        "ok": True,
                        "action": action_name,
                        "target": tuple(bet_btn_coords),
                        "bet_size": amount_to_bet,
                    }
                logger.error("CLICK_RESULT | action=%s status=failed reason=bet_button_click_failed", action_name)
                return {
                    "ok": False,
                    "action": action_name,
                    "reason": "bet_button_click_failed",
                    "target": tuple(bet_btn_coords),
                    "bet_size": amount_to_bet,
                }
                
            return await self._execute_with_retry(_attempt_full_bet_sequence)"""
            
    content = content.replace(old_block, new_block)
    
    with open("src/bot/action_controller.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Action controller updated successfully!")
else:
    print("Regex failed to find the bet block.")
