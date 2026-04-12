import asyncio
import logging
import base64
import os
import cv2
import numpy as np
from datetime import datetime

# On réutilise l'outil qu'on a déjà créé pour interroger les API
from src.vision.auto_annotator import AutoAnnotator

logger = logging.getLogger("ActiveLearning")

class HumanInTheLoop:
    def __init__(self, target_dataset_size: int = 100):
        self.target_dataset_size = target_dataset_size
        self.dataset_dir_images = "dataset/raw_images"
        self.dataset_dir_labels = "dataset/labels"
        
        # S'assurer que les dossiers existent
        os.makedirs(self.dataset_dir_images, exist_ok=True)
        os.makedirs(self.dataset_dir_labels, exist_ok=True)
        
        # Compter les images déjà annotées
        self.annotations_count = len([f for f in os.listdir(self.dataset_dir_labels) if f.endswith('.txt')])
        
        # États de synchronisation
        self.intervention_event = asyncio.Event()
        self.current_issue = None
        self.is_waiting_for_human = False
        
        # L'annotateur de secours (Initialisé dans _setup_api_fallback)
        self.ai_fallback: AutoAnnotator = None

    def setup_api_fallback(self, api_key: str, base_url: str, model: str):
        """Configure le LLM Vision de secours pour l'auto-guérison."""
        if api_key or base_url:
            self.ai_fallback = AutoAnnotator(api_key=api_key, base_url=base_url, model=model)
            logger.info(f"Auto-Adaptation API configurée avec le modèle {model}")

    def _save_to_dataset(self, frame: np.ndarray, yolo_label_content: str):
        """Sauvegarde la frame et le label pour le prochain entraînement local."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        img_path = os.path.join(self.dataset_dir_images, f"active_learn_{timestamp}.jpg")
        lbl_path = os.path.join(self.dataset_dir_labels, f"active_learn_{timestamp}.txt")
        
        cv2.imwrite(img_path, frame)
        with open(lbl_path, "w") as f:
            f.write(yolo_label_content)
            
        self.annotations_count += 1
        logger.info(f"Nouvelle donnée ajoutée au dataset ({self.annotations_count}/{self.target_dataset_size})")

    async def request_intervention(self, frame: np.ndarray, issue_type: str, reason: str) -> dict:
        """
        Déclencheé quand le bot local (YOLO) est perdu.
        Tente d'abord l'Auto-Adaptation via API, sinon bascule sur le Humain.
        """
        logger.warning(f"Anomalie détectée: {issue_type} - {reason}")
        
        height, width = frame.shape[:2]
        
        # ETAPE 1: Auto-Guérison par API (Si configurée)
        if self.ai_fallback:
            logger.info("Tentative d'Auto-Guérison via l'API Vision...")
            
            # Sauvegarder temporairement l'image pour l'API
            temp_path = "temp_fallback.jpg"
            cv2.imwrite(temp_path, frame)
            
            # On décharge cet appel lourd dans un thread pour ne pas bloquer asyncio
            boxes = await asyncio.to_thread(self.ai_fallback.ask_ai_for_bounding_boxes, temp_path, width, height)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            if boxes and len(boxes) > 0:
                logger.info("Auto-Guérison API Réussie ! Le bot s'est adapté.")
                yolo_txt = self.ai_fallback.convert_to_yolo_format(boxes, width, height)
                self._save_to_dataset(frame, yolo_txt)
                
                # On retourne un faux résultat positif pour permettre au bot de continuer sa main
                return {"status": "resolved_by_api", "boxes": boxes}
            else:
                logger.warning("L'API Vision n'a pas pu résoudre le problème.")

        # ETAPE 2: Fallback Humain (Si l'API a échoué ou n'est pas configurée)
        logger.info("Mise en pause du bot. Demande d'intervention humaine envoyée à la GUI.")
        
        # Encodage de l'image pour la GUI (Web)
        _, buffer = cv2.imencode('.jpg', frame)
        base64_image = base64.b64encode(buffer).decode('utf-8')
        
        self.current_issue = {
            "type": issue_type,
            "reason": reason,
            "image_base64": base64_image,
            "width": width,
            "height": height,
            "raw_frame": frame
        }
        
        self.is_waiting_for_human = True
        self.intervention_event.clear()
        
        # Gèle l'exécution de la boucle principale de Poker jusqu'à ce que l'humain réponde via l'API
        await self.intervention_event.wait()
        
        return self.current_issue.get("resolution", {"status": "skipped"})

    def resolve_human_intervention(self, human_boxes: list):
        """
        Appelé par l'interface Web/Tauri quand l'utilisateur a dessiné la réponse.
        """
        if not self.is_waiting_for_human or not self.current_issue:
            return

        frame = self.current_issue["raw_frame"]
        width = self.current_issue["width"]
        height = self.current_issue["height"]
        
        # Création d'un AutoAnnotator factice juste pour utiliser sa méthode de formatage
        dummy_annotator = AutoAnnotator(api_key="") 
        yolo_txt = dummy_annotator.convert_to_yolo_format(human_boxes, width, height)
        
        self._save_to_dataset(frame, yolo_txt)
        
        self.current_issue["resolution"] = {"status": "resolved_by_human", "boxes": human_boxes}
        self.is_waiting_for_human = False
        
        # Débloque le bot
        self.intervention_event.set()

    def check_convergence(self) -> bool:
        """Retourne True si on a récolté assez d'images pour ré-entraîner le modèle local."""
        return self.annotations_count >= self.target_dataset_size