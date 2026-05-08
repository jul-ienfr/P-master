import cv2
import numpy as np

class FastPixelProbe:
    """
    Sonde ultra-légère au niveau pixel pour de la détection rapide (ex: à qui est le tour)
    sans avoir besoin d'invoquer tout l'OCR ou YOLO.
    """
    def __init__(self):
        pass

    @staticmethod
    def is_our_turn(frame: np.ndarray) -> bool:
        """
        Détecte rapidement si c'est le tour du Hero en scrutant l'apparition des boutons d'action.
        On analyse la couleur rouge "vif" ou jaune "vif" dans la zone standard des boutons.
        """
        if frame is None or len(frame.shape) != 3:
            return False

        h, w, _ = frame.shape
        # Zone typique des boutons d'action (en bas à droite)
        roi_x = int(w * 0.6)
        roi_y = int(h * 0.8)
        roi_w = int(w * 0.4)
        roi_h = int(h * 0.2)

        # S'assurer de ne pas déborder
        roi_x2 = min(roi_x + roi_w, w)
        roi_y2 = min(roi_y + roi_h, h)

        roi = frame[roi_y:roi_y2, roi_x:roi_x2]
        if roi.size == 0:
            return False

        # Conversion HSV pour cibler la couleur rouge vif des boutons Fold (ou similaire)
        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Plages HSV pour un rouge PokerStars/Winamax
        # Le rouge boucle dans les teintes HSV, donc 2 plages
        lower_red_1 = np.array([0, 150, 150])
        upper_red_1 = np.array([10, 255, 255])

        lower_red_2 = np.array([170, 150, 150])
        upper_red_2 = np.array([180, 255, 255])

        mask1 = cv2.inRange(hsv_roi, lower_red_1, upper_red_1)
        mask2 = cv2.inRange(hsv_roi, lower_red_2, upper_red_2)
        red_mask = cv2.bitwise_or(mask1, mask2)

        # Si de nombreux pixels rouges sont détectés dans la zone des boutons, on estime que c'est notre tour.
        red_pixels_ratio = cv2.countNonZero(red_mask) / (roi_w * roi_h + 1e-5)

        # Le 0.02 (2%) est heuristique et dépend de l'interface
        return red_pixels_ratio > 0.02
