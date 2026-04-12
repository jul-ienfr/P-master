class PreflopManager:
    """
    Gère les ranges Pré-Flop GTO en fonction de la position du Hero à la table (6-Max).
    Format standard: UTG (Under The Gun), HJ (Hijack), CO (Cut-off), BTN (Button), SB (Small Blind), BB (Big Blind).
    """
    def __init__(self):
        # Ranges d'Open Raise (RFI - Raise First In) pour du 6-Max Cash Game
        self.rfi_ranges = {
            "UTG": "77+, ATs+, KTs+, QTs+, JTs, T9s, 98s, 87s, 76s, AJo+, KQo", # Très serré (15%)
            "HJ":  "55+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, 65s, ATo+, KJo+, QJo", # ~20%
            "CO":  "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, 54s, A9o+, KTo+, QTo+, JTo", # ~28%
            "BTN": "22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K8o+, Q9o+, J9o+, T9o", # ~45% (Vol de blindes)
            "SB":  "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 87s, 76s, 65s, 54s, A2o+, K9o+, QTo+, JTo", # ~35%
        }
        
        # Défense basique contre un Open Raise (Call ou 3-bet)
        self.defense_ranges = {
            "BB": "22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A7o+, K9o+, QTo+, JTo" # Défense très large car on a déjà mis 1 BB
        }

    def get_hero_range(self, position: str, facing_raise: bool = False) -> str:
        """Retourne la range mathématiquement correcte selon la position."""
        pos_upper = position.upper() if position else "BTN"
        
        # Si on fait face à une relance, on resserre drastiquement, sauf en Big Blind
        if facing_raise:
            if pos_upper == "BB":
                return self.defense_ranges["BB"]
            # Contre une relance, on 3-bet ou on fold (simplified 3-bet or fold strategy)
            return "TT+, AQs+, AKo" 

        # Par défaut, on retourne la range d'ouverture
        return self.rfi_ranges.get(pos_upper, self.rfi_ranges["BTN"])

    def get_villain_range(self, villain_position: str, action: str = "OPEN") -> str:
        """Estime la range de l'adversaire selon sa position et son action (pour le Node-Locking du solveur)."""
        v_pos = villain_position.upper() if villain_position else "UTG"
        
        if action == "OPEN":
            return self.rfi_ranges.get(v_pos, self.rfi_ranges["HJ"])
        elif action == "3BET":
            return "JJ+, AQs+, AKo" # Range typique de 3-bet d'un joueur moyen
            
        return self.rfi_ranges["BTN"] # Fallback large
