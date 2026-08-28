import re

with open("src/bot/action_controller.py", "r", encoding="utf-8") as f:
    code = f.read()

old_func = """            async def _attempt_full_bet_sequence(attempt_idx: int) -> dict:
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
                
                # CLOSED-LOOP VALIDATION
                if bet_validation_callback is not None:
                    is_valid_bet = await bet_validation_callback(amount_to_bet)
                    if not is_valid_bet:
                        logger.warning(f"Validation en boucle fermée échouée: Le montant tapé semble incorrect par rapport à {amount_to_bet}.")
                        return {"ok": False, "action": action_name, "reason": "closed_loop_bet_validation_failed"}

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
"""

code = re.sub(
    r'            async def _attempt_full_bet_sequence\(attempt_idx: int\) -> dict:.*?(?=            return await self\._execute_with_retry)', 
    old_func,
    code, flags=re.DOTALL
)

with open("src/bot/action_controller.py", "w", encoding="utf-8") as f:
    f.write(code)
