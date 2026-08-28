import re

with open('src/bot/action_controller.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. HWND Lock
old_find = """    def _find_window(self):
        \"\"\"Cherche le handle (HWND) de la fenêtre cible.\"\"\"
        previous_hwnd = self.hwnd
        previous_title = self.window_title
        primary_keywords = _parse_window_title_keywords(self.window_title_keywords)
        best_match = self._select_best_window(primary_keywords)"""

new_find = """    def _find_window(self):
        \"\"\"Cherche le handle (HWND) de la fenêtre cible.\"\"\"
        primary_keywords = _parse_window_title_keywords(self.window_title_keywords)
        
        # LOCK HWND: Empêcher de sauter sur une autre fenêtre si celle-ci est toujours valide
        if getattr(self, 'hwnd', None) and win32gui.IsWindow(self.hwnd):
            try:
                current_title = win32gui.GetWindowText(self.hwnd)
                if self._score_window_title(current_title, primary_keywords) > 0:
                    self.window_title = current_title
                    return
            except Exception:
                pass

        previous_hwnd = self.hwnd
        previous_title = self.window_title
        best_match = self._select_best_window(primary_keywords)"""

text = text.replace(old_find, new_find)

# 2. Bezier & Fitts's law
old_mouse = """    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=0.3):
        \"\"\"
        Génère un mouvement de souris fluide entre deux points (approximation Bézier/Ease-out)
        au lieu d'une téléportation robotique. Asynchrone pour ne pas bloquer l'event loop.
        \"\"\"
        steps = int(duration * 60) # 60 Hz
        if steps == 0: steps = 1
        
        # Ajout d'un léger over-shoot aléatoire pour simuler l'imperfection humaine
        control_x = (start_x + target_x) / 2 + random.randint(-50, 50)
        control_y = (start_y + target_y) / 2 + random.randint(-50, 50)

        for i in range(1, steps + 1):
            t = i / steps
            # Formule de Bézier quadratique
            x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            
            # Déplacer physiquement la souris
            win32api.SetCursorPos((x, y))
            await asyncio.sleep(duration / steps)"""

new_mouse = """    def _ease_out_quad(self, t):
        return t * (2 - t)

    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=None):
        \"\"\"
        Génère un mouvement de souris fluide basé sur la loi de Fitts et Bézier, 
        avec un potentiel dépassement (overshoot) pour leurrer les anti-cheats.
        \"\"\"
        distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
        if duration is None:
            duration = min(max(distance / random.uniform(800, 1500), 0.2), 0.8)
        
        steps = max(5, int(duration * 60))
        
        control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7) + random.randint(-150, 150)
        control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7) + random.randint(-150, 150)

        for i in range(1, steps + 1):
            t = i / steps
            x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            win32api.SetCursorPos((x, y))
            await asyncio.sleep(duration / steps)
            
        if random.random() < 0.40:
            ox = target_x + random.randint(-15, 15)
            oy = target_y + random.randint(-15, 15)
            
            o_steps = max(3, int(0.12 * 60))
            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(target_x + (ox - target_x) * t)
                y = int(target_y + (oy - target_y) * t)
                win32api.SetCursorPos((x, y))
                await asyncio.sleep(0.12 / o_steps)
                
            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(ox + (target_x - ox) * t)
                y = int(oy + (target_y - oy) * t)
                win32api.SetCursorPos((x, y))
                await asyncio.sleep(0.12 / o_steps)"""

text = text.replace(old_mouse, new_mouse)

# 3. Dynamic Think Time
old_think = """        # Délai de réflexion humain avant de jouer (très important pour les anti-cheats)
        think_time = random.uniform(MIN_THINK_TIME_S, MAX_THINK_TIME_S)
        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)"""

new_think = """        # Délai de réflexion humain proportionnel à l'action
        if action_name == "FOLD":
            think_time = random.uniform(1.0, 2.5)
        elif action_name in ["CHECK", "CALL"] and action_intent.bet_size is None:
            think_time = random.uniform(2.0, 4.5)
        else:
            think_time = random.uniform(4.0, 12.0)
            
        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)"""

text = text.replace(old_think, new_think)

with open('src/bot/action_controller.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated action_controller.py successfully via script.")
