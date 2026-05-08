import re

with open('src/bot/action_controller.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update execute_action to accept retry mechanism
new_execute_action = """    async def _execute_with_retry(self, action_func, max_retries=2) -> dict:
        \"\"\"Execute une action réseau/souris avec un système de retry basique.
        Ajoute un jitter spatial si le clic échoue.
        \"\"\"
        last_result = {"ok": False, "reason": "unknown"}
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.warning(f"RETRY_ACTION | attempt={attempt}/{max_retries}")
                await asyncio.sleep(random.uniform(0.1, 0.3))
                
            result = await action_func(attempt)
            if result.get("ok"):
                return result
            last_result = result
            
        return last_result

    async def execute_action(self, action_request, coords_mapping: dict):
        if isinstance(action_request, ActionIntent):
            action_intent = action_request
        else:
            action_intent = ActionIntent.from_payload(action_request)

        action_name = action_intent.action
        logger.info(
            "ACTION_REQUEST | action=%s bet_size=%s targets=%s",
            action_name,
            action_intent.bet_size,
            sorted(key for key, value in (coords_mapping or {}).items() if value),
        )
        
        # Délai de réflexion humain avant de jouer (très important pour les anti-cheats)
        think_time = random.uniform(MIN_THINK_TIME_S, MAX_THINK_TIME_S)
        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)
        
        async def _attempt_click(coords, name, attempt_idx):
            # Jittering spatial pendant le retry pour éviter de retomber exactement sur le même mauvais pixel
            jitter_x = random.randint(-3, 3) if attempt_idx > 0 else 0
            jitter_y = random.randint(-3, 3) if attempt_idx > 0 else 0
            
            clicked = await self.click_at(coords[0] + jitter_x, coords[1] + jitter_y)
            if clicked:
                logger.info(f"-> Action exécutée : {name}")
                return {"ok": True, "action": name, "target": tuple(coords)}
            logger.error(f"CLICK_RESULT | action={name} status=failed reason={name.lower()}_click_failed")
            return {"ok": False, "action": name, "reason": f"{name.lower()}_click_failed", "target": tuple(coords)}

        if action_name == "FOLD":
            coords = coords_mapping.get("FOLD")
            if coords:
                return await self._execute_with_retry(lambda attempt: _attempt_click(coords, "FOLD", attempt))
            logger.warning("CLICK_RESULT | action=FOLD status=skipped reason=missing_fold_coords")
            return {"ok": False, "action": "FOLD", "reason": "missing_fold_coords"}
                
        elif action_name == "CALL" or action_name == "CHECK":
            coords = coords_mapping.get("CALL")
            if coords:
                return await self._execute_with_retry(lambda attempt: _attempt_click(coords, action_name, attempt))
            logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_call_coords", action_name)
            return {"ok": False, "action": action_name, "reason": "missing_call_coords"}
                
        elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:
            text_box_coords = coords_mapping.get("BET_BOX")
            if text_box_coords:
                # La logique complexe (Double clique + texte + bouton) reste dans la boucle principale mais on encapsule le retry sur le clique final
                clicked = await self.click_at(*text_box_coords, double_click=True)
                if not clicked:
                    logger.error("CLICK_RESULT | action=%s status=failed reason=bet_box_click_failed", action_name)
                    return {"ok": False, "action": action_name, "reason": "bet_box_click_failed"}
                
                amount_to_bet = str(action_intent.bet_size if action_intent.bet_size is not None else 5.50)
                await self.send_text(amount_to_bet)
                
                bet_btn_coords = coords_mapping.get("BET_BTN")
                if bet_btn_coords:
                    await asyncio.sleep(random.uniform(0.08, 0.16))
                    
                    async def _attempt_bet_click(attempt_idx):
                        jitter_x = random.randint(-3, 3) if attempt_idx > 0 else 0
                        jitter_y = random.randint(-3, 3) if attempt_idx > 0 else 0
                        
                        clicked_btn = await self.click_at(bet_btn_coords[0] + jitter_x, bet_btn_coords[1] + jitter_y)
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
                        
                    return await self._execute_with_retry(_attempt_bet_click)

                logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_bet_button_coords", action_name)
                return {"ok": False, "action": action_name, "reason": "missing_bet_button_coords"}
            logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_bet_box_coords", action_name)
            return {"ok": False, "action": action_name, "reason": "missing_bet_box_coords"}

        logger.warning("CLICK_RESULT | action=%s status=skipped reason=unsupported_action", action_name)
        return {"ok": False, "action": action_name, "reason": "unsupported_action"}"""

content = re.sub(r'    async def execute_action\(self, action_request.*?return \{"ok": False, "action": action_name, "reason": "unsupported_action"\}', new_execute_action, content, flags=re.DOTALL)

with open('src/bot/action_controller.py', 'w', encoding='utf-8') as f:
    f.write(content)
