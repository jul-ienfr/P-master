import dxcam
import cv2
import numpy as np
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class ScreenCapture:
    def __init__(self, target_fps: int = 2):
        """
        Initialise la capture d'écran via DirectX.
        
        Args:
            target_fps: Le nombre d'images par seconde souhaité. 
                        Pour le poker, 2 fps (une frame toutes les 0.5s) est l'idéal absolu
                        pour économiser 100% du CPU tout en réagissant assez vite.
        """
        self.target_fps = target_fps
        # dxcam instancie la capture sur le moniteur principal par défaut
        try:
            self.camera = dxcam.create(output_color="BGR")
            logger.info("DXcam initialisé avec succès (Color space: BGR pour OpenCV)")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de DXcam: {e}")
            self.camera = None
            
        self.is_capturing = False

    def start(self, region: Optional[Tuple[int, int, int, int]] = None):
        """
        Démarre la capture d'écran en continu.
        
        Args:
            region: Tuple (left, top, right, bottom) définissant la zone de la table de poker.
                    Si None, capture tout l'écran.
        """
        if not self.camera:
            return False

        if not self.is_capturing:
            self.camera.start(target_fps=self.target_fps, region=region)
            self.is_capturing = True
            area = f"Région: {region}" if region else "Plein écran"
            logger.info(f"Capture démarrée à {self.target_fps} FPS ({area})")
        return True

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Récupère la dernière image capturée (non-bloquant).
        Retourne None si aucune nouvelle image n'est disponible.
        """
        if not self.camera or not self.is_capturing:
            return None
        
        # get_latest_frame est thread-safe et retourne la frame en RAM
        return self.camera.get_latest_frame()

    def stop(self):
        """Arrête la capture."""
        if self.camera and self.is_capturing:
            self.camera.stop()
            self.is_capturing = False
            logger.info("Capture DirectX arrêtée.")

# Exemple d'utilisation rapide si le script est exécuté directement
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cap = ScreenCapture(target_fps=2)
    
    # On démarre la capture (sur tout l'écran pour le test)
    if cap.start():
        try:
            print("Capture en cours... Appuyez sur 'q' dans la fenêtre pour quitter.")
            while True:
                frame = cap.get_latest_frame()
                if frame is not None:
                    # On affiche la frame réduite pour le test
                    preview = cv2.resize(frame, (960, 540))
                    cv2.imshow("Poker Bot - DXcam Preview", preview)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        finally:
            cap.stop()
            cv2.destroyAllWindows()
