class PreflopManager:
    """
    Gère les ranges Pré-Flop GTO en fonction de la position du Hero à la table (6-Max).
    Format standard: UTG (Under The Gun), HJ (Hijack), CO (Cut-off), BTN (Button), SB (Small Blind), BB (Big Blind).

    ``heads_up=True`` bascule sur les ranges HU (SB = bouton) : le SB ouvre et
    défend beaucoup plus large qu'en 6-max, où les charts 3-bet-or-fold
    abandonnent ~95 % des mains face à une relance. Le mode reste opt-in
    (``POKER_TABLE_MODE=hu``) pour ne pas changer le comportement 6-max.
    """

    def __init__(self, heads_up: bool = False):
        self.heads_up = bool(heads_up)

        # Ranges heads-up 100 bb (SB = bouton). Le SB HU ouvre ~78 % des mains ;
        # le BB défend ~85 % face à une ouverture ; le SB ne défend que ~30 %
        # face à un 3-bet (4-bet ou call).
        self.hu_rfi_ranges = {
            "SB": (
                "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, "
                "52s+, 42s+, 32s, A2o+, K2o+, Q2o+, J3o+, T5o+, 95o+, 85o+, "
                "75o+, 64o+, 54o, 43o"
            ),
            "BB": (
                "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, "
                "52s+, 42s+, 32s, A2o+, K2o+, Q2o+, J2o+, T2o+, 93o+, 83o+, "
                "73o+, 63o+, 53o+, 43o"
            ),
        }
        self.hu_defense_ranges = {
            "BB": (
                "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, "
                "52s+, 42s+, 32s, A2o+, K2o+, Q2o+, J2o+, T2o+, 93o+, 83o+, "
                "73o+, 63o+, 53o+, 43o"
            ),
            "SB": (
                "22+, A2s+, K5s+, Q7s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, "
                "A8o+, KTo+, QTo+, JTo"
            ),
        }

        # Ranges d'Open Raise (RFI - Raise First In) pour du 6-Max Cash Game
        self.rfi_ranges = {
            "UTG": "77+, ATs+, KTs+, QTs+, JTs, T9s, 98s, 87s, 76s, AJo+, KQo",  # Très serré (15%)
            "HJ": "55+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, 65s, ATo+, KJo+, QJo",  # ~20%
            "CO": "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, 54s, A9o+, KTo+, QTo+, JTo",  # ~28%
            "BTN": "22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K8o+, Q9o+, J9o+, T9o",  # ~45% (Vol de blindes)
            "SB": "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 87s, 76s, 65s, 54s, A2o+, K9o+, QTo+, JTo",  # ~35%
        }

        # Défense basique contre un Open Raise (Call ou 3-bet)
        self.defense_ranges = {
            "BB": "22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A7o+, K9o+, QTo+, JTo"  # Défense très large car on a déjà mis 1 BB
        }

    def hu_position(self, position: str) -> str:
        """Aligne les libellés de position sur les ranges HU (bouton = SB).

        Le tracker et les harnais annoncent souvent « BTN » en heads-up, alors
        que les ranges HU sont indexées « SB » (le bouton est la petite blind).
        Sans cet alias, le bouton retombait sur les charts 6-max et se couchait
        face à sa propre blind.
        """
        pos_upper = position.upper() if position else "BTN"
        if not self.heads_up:
            return pos_upper
        return {"BTN": "SB", "SB": "SB", "BB": "BB"}.get(pos_upper, pos_upper)

    def get_hero_range(self, position: str, facing_raise: bool = False) -> str:
        """Retourne la range mathématiquement correcte selon la position."""
        pos_upper = self.hu_position(position)

        if self.heads_up and pos_upper in self.hu_rfi_ranges:
            if facing_raise:
                return self.hu_defense_ranges.get(pos_upper, self.hu_defense_ranges["BB"])
            return self.hu_rfi_ranges[pos_upper]

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
        if self.heads_up:
            v_pos = {"BTN": "SB", "SB": "SB", "BB": "BB"}.get(v_pos, v_pos)

        if self.heads_up and v_pos in self.hu_rfi_ranges:
            if action == "3BET":
                return "JJ+, AQs+, AKo"
            return self.hu_rfi_ranges[v_pos]

        if action == "OPEN":
            return self.rfi_ranges.get(v_pos, self.rfi_ranges["HJ"])
        elif action == "3BET":
            return "JJ+, AQs+, AKo"  # Range typique de 3-bet d'un joueur moyen

        return self.rfi_ranges["BTN"]  # Fallback large
