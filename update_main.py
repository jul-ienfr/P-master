import re

with open("src/main.py", "r") as f:
    content = f.read()

jit_func = """
    async def _jit_action_validator(self) -> bool:
        \"\"\"
        Vérification Just-In-Time (JIT) de l'état de l'écran juste avant le clic physique.
        Retourne `False` si la zone d'action a visuellement muté, annulant ainsi l'action obsolete.
        \"\"\"
        try:
            # On force un rafraîchissement manuel de la région si nécessaire
            frame = self.camera.get_latest_frame()
            if frame is None:
                return False
            
            visual_changed, _, changed_regions = self._detect_relevant_visual_change(frame)
            if visual_changed and "actions" in changed_regions:
                return False
            return True
        except Exception as e:
            return False
"""

# Insert _jit_action_validator before _wait_for_action_settle
content = content.replace(
    "    async def _wait_for_action_settle(self) -> dict:",
    jit_func + "\n    async def _wait_for_action_settle(self) -> dict:"
)

# Update execute_action call to include jit_check
old_call = "execution_result = await self.action_controller.execute_action(action_intent, dynamic_coords)"
new_call = """try:
                    execution_result = await self.action_controller.execute_action(
                        action_intent, 
                        dynamic_coords, 
                        jit_check=self._jit_action_validator
                    )
                except Exception as jit_err:
                    if "JIT Check Failed" in str(jit_err):
                        self._clear_live_decision_summary(canonical_state)
                        self.last_decision_summary["execution"] = {
                            "status": "aborted_jit",
                            "reason": "JIT Check Failed",
                        }
                        logger.warning("CLICK | aborted_jit action=%s", decision.get("action", ""))
                        self._push_incident("jit_abort", severity="warning", reason="Actions region mutated")
                        execution_result = {"ok": False, "reason": "JIT Abort"}
                    else:
                        raise"""
                        
content = content.replace(old_call, new_call)

with open("src/main.py", "w") as f:
    f.write(content)
