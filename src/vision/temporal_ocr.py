import logging
from collections import deque
from typing import Optional, Deque, List
import numpy as np

from src.vision.ocr import PokerOCR

logger = logging.getLogger(__name__)

class TemporalOCRFilter:
    """
    Bouclier anti-hallucination OCR basé sur le lissage temporel.
    Stocke les N dernières lectures d'une zone (ex: le pot) et 
    ne valide une nouvelle valeur que si elle est stable sur plusieurs frames.
    """
    def __init__(self, history_size: int = 3, engine_mode: str = "consensus_amounts", enabled_engines: List[str] = None):
        self.history_size = history_size
        self._amount_history: Deque[float] = deque(maxlen=history_size)
        self._text_history: Deque[str] = deque(maxlen=history_size)
        
        # Instance sous-jacente du moteur OCR multi-engines
        self.ocr_engine = PokerOCR(
            enabled_engines=enabled_engines,
            mode=engine_mode,
            parallel=True
        )

    def read_stable_amount(self, image_crop: np.ndarray, tolerance: float = 0.05, chip_count: Optional[int] = None) -> Optional[float]:
        """
        Lit un montant et le lisse temporellement.
        tolérance: Différence acceptable (en %) pour considérer que deux lectures sont "les mêmes".
        chip_count: Nombre de piles de jetons (YOLO) détectées dans la même zone (Sanity Check visuel).
        """
        raw_amount = self.ocr_engine.read_and_parse_amount(image_crop)
        
        # --- Sanity Check YOLO vs OCR ---
        if raw_amount is not None and chip_count is not None:
            if chip_count == 0 and raw_amount > 0.0:
                logger.warning(f"Sanity Check Echoue: L'OCR lit {raw_amount} mais YOLO ne voit AUCUN jeton (chip_count=0).")
        
        if raw_amount is None:
            # Si on ne lit rien, on ne casse pas l'historique tout de suite
            return self._get_consensus_amount()
            
        self._amount_history.append(raw_amount)
        
        # S'il nous manque de l'historique, on retourne la valeur brute
        if len(self._amount_history) < self.history_size:
            return raw_amount
            
        return self._get_consensus_amount(tolerance)

    def _get_consensus_amount(self, tolerance: float = 0.05) -> Optional[float]:
        """Extrait la valeur la plus stable de l'historique récent."""
        if not self._amount_history:
            return None
            
        recent_values = list(self._amount_history)
        
        # On cherche s'il y a un consensus majoritaire
        for val in set(recent_values):
            # Compte combien de valeurs dans l'historique sont "proches" de 'val'
            similar_count = sum(1 for v in recent_values if abs(v - val) <= (val * tolerance + 0.01))
            
            # Si plus de la moitié des frames (ex: 2 sur 3) voient ce montant, on le valide
            if similar_count >= (self.history_size / 2.0):
                return val
                
        # Pas de consensus temporel clair : 
        # On protège le système en renvoyant None plutôt qu'une hallucination
        logger.debug(f"Instabilité temporelle OCR détectée. Historique: {recent_values}")
        return None

    def read_stable_text(self, image_crop: np.ndarray) -> str:
        """Lit un texte de manière stable (utile pour les noms de joueurs/actions)"""
        raw_text = self.ocr_engine.read_text(image_crop)
        
        if not raw_text:
            return self._get_consensus_text()
            
        self._text_history.append(raw_text)
        
        if len(self._text_history) < self.history_size:
            return raw_text
            
        return self._get_consensus_text()

    def _get_consensus_text(self) -> str:
        if not self._text_history:
            return ""
            
        from collections import Counter
        # Pour le texte, on veut une correspondance exacte
        counts = Counter(self._text_history)
        most_common_text, count = counts.most_common(1)[0]
        
        if count >= (self.history_size / 2.0):
            return most_common_text
            
        return ""
        
    def reset_history(self):
        """A appeler au changement de street ou de main pour vider le cache temporel."""
        self._amount_history.clear()
        self._text_history.clear()
