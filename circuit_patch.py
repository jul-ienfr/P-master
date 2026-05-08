import re

with open("src/bot/decision_maker.py", "r", encoding="utf-8") as f:
    code = f.read()

init_replacement = """    def __init__(
        self,
        db_manager,
        solver_backend: Any = _DEFAULT_DEPENDENCY,
        rl_agent: Any = _DEFAULT_DEPENDENCY,
        create_rl_agent: bool = True,
        enable_validated_rl: bool = False,
        autoload_rl_model: bool = True,
    ):
        self.db = db_manager
        self.icm_calculator = ICMCalculator()
        self.preflop_manager = PreflopManager()
        self.solver_backend = postflop_solver_py if solver_backend is _DEFAULT_DEPENDENCY and RUST_SOLVER_AVAILABLE else None if solver_backend is _DEFAULT_DEPENDENCY else solver_backend
        
        self.hero_base_range = BASE_GTO_RANGE
        
        # Circuit Breaker variables
        self._consecutive_solver_timeouts = 0
        self._solver_cooldown_until = 0.0
"""

code = code.replace("""    def __init__(
        self,
        db_manager,
        solver_backend: Any = _DEFAULT_DEPENDENCY,
        rl_agent: Any = _DEFAULT_DEPENDENCY,
        create_rl_agent: bool = True,
        enable_validated_rl: bool = False,
        autoload_rl_model: bool = True,
    ):
        self.db = db_manager
        self.icm_calculator = ICMCalculator()
        self.preflop_manager = PreflopManager()
        self.solver_backend = postflop_solver_py if solver_backend is _DEFAULT_DEPENDENCY and RUST_SOLVER_AVAILABLE else None if solver_backend is _DEFAULT_DEPENDENCY else solver_backend
        
        self.hero_base_range = BASE_GTO_RANGE""", init_replacement)

action_replacement = """    async def get_best_action(self, hero_hand: str, board: List[str], pot: float, 
                              effective_stack: float, villain_name: str, 
                              legal_actions: List[str], spot_id: str = "",
                              hero_position: str = "ip", state_confidence: float = 0.0,
                              action_history: Optional[List[Dict[str, Any]]] = None,
                              tournament_data: Optional[Dict[str, Any]] = None) -> dict:
        \"\"\"
        Détermine la meilleure action à prendre en combinant GTO (Solver Rust), 
        Reinforcement Learning (Agent RL), Node-Locking, et ICM.
        \"\"\"
        logger.info(f"Calcul de décision contre {villain_name}. Board: {board}, Pot: {pot}")
        hero_hand = _normalize_hero_hand_string(hero_hand)
        legal_actions = self._normalize_runtime_actions(legal_actions)
        if not legal_actions:
            return self._fallback_action([])
            
        # CIRCUIT BREAKER CHECK
        if time.monotonic() < self._solver_cooldown_until:
            logger.error("🛑 CIRCUIT BREAKER ACTIF: Solver en cooldown. Auto-Fallback.")
            return self._fallback_action(legal_actions)
"""

code = code.replace("""    async def get_best_action(self, hero_hand: str, board: List[str], pot: float, 
                              effective_stack: float, villain_name: str, 
                              legal_actions: List[str], spot_id: str = "",
                              hero_position: str = "ip", state_confidence: float = 0.0,
                              action_history: Optional[List[Dict[str, Any]]] = None,
                              tournament_data: Optional[Dict[str, Any]] = None) -> dict:
        \"\"\"
        Détermine la meilleure action à prendre en combinant GTO (Solver Rust), 
        Reinforcement Learning (Agent RL), Node-Locking, et ICM.
        \"\"\"
        logger.info(f"Calcul de décision contre {villain_name}. Board: {board}, Pot: {pot}")
        hero_hand = _normalize_hero_hand_string(hero_hand)
        legal_actions = self._normalize_runtime_actions(legal_actions)
        if not legal_actions:
            return self._fallback_action([])""", action_replacement)
            
get_best_action_middle = """            except asyncio.TimeoutError:
                logger.error("Solver Rust timeout (>10s). Fail-safe to FOLD/CHECK.")
                self._consecutive_solver_timeouts += 1
                if self._consecutive_solver_timeouts >= 3:
                    logger.critical("🛑 CIRCUIT BREAKER DÉCLENCHÉ : Trop de timeouts Rust consécutifs. Mise en cooldown 60s.")
                    self._solver_cooldown_until = time.monotonic() + 60.0
                fallback_used = True
                fallback_reason = "solver_timeout"
                gto_action = "CHECK" if "CHECK" in legal_actions else "FOLD"
            except Exception as e:
                logger.error(f"Erreur lors de l'appel au Solver Rust: {e}")
                fallback_used = True
                fallback_reason = str(e)
        else:
            fallback_used = True
            fallback_reason = "rust_solver_unavailable"
            
        # Résilience: si la requête réussit, on reset le circuit breaker
        if not fallback_used:
            self._consecutive_solver_timeouts = 0
"""
            
code = re.sub(
    r'            except asyncio\.TimeoutError:\n                logger\.error\("Solver Rust timeout \(>10s\)\. Fail-safe to FOLD/CHECK\."\)\n                fallback_used = True\n                fallback_reason = "solver_timeout"\n                gto_action = "CHECK" if "CHECK" in legal_actions else "FOLD"\n            except Exception as e:\n                logger\.error\(f"Erreur lors de l\'appel au Solver Rust: \{e\}"\)\n                fallback_used = True\n                fallback_reason = str\(e\)\n        else:\n            fallback_used = True\n            fallback_reason = "rust_solver_unavailable"',
    get_best_action_middle,
    code, flags=re.DOTALL
)

with open("src/bot/decision_maker.py", "w", encoding="utf-8") as f:
    f.write(code)
