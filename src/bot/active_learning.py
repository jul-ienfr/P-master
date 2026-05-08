import asyncio
import logging
import base64
import json
import os
from pathlib import Path
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
        self.shadow_dir = Path("dataset/shadow_failures")
        self.shadow_manifest_path = self.shadow_dir / "events.jsonl"
        
        # S'assurer que les dossiers existent
        os.makedirs(self.dataset_dir_images, exist_ok=True)
        os.makedirs(self.dataset_dir_labels, exist_ok=True)
        self.shadow_dir.mkdir(parents=True, exist_ok=True)
        
        # Compter les images déjà annotées
        self.annotations_count = len([f for f in os.listdir(self.dataset_dir_labels) if f.endswith('.txt')])
        
        # États de synchronisation
        self.intervention_event = asyncio.Event()
        self.current_issue = None
        self.is_waiting_for_human = False
        
        # L'annotateur de secours (Initialisé dans _setup_api_fallback)
        self.ai_fallback: AutoAnnotator = None

    def setup_api_fallback(self, providers: list):
        """Configure le LLM Vision de secours pour l'auto-guérison."""
        if providers:
            self.ai_fallback = AutoAnnotator(providers=providers)
            logger.info(f"Auto-Adaptation API configurée avec {len(providers)} fournisseurs.")
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

    async def request_intervention_async(self, frame: np.ndarray, issue_type: str, reason: str):
        """
        Déclencheé quand le bot local (YOLO) est perdu. Background task non-bloquante.
        """
        if self.is_waiting_for_human:
            return  # Une requête est déjà en cours

        logger.warning(f"Anomalie détectée (Async): {issue_type} - {reason}")
        height, width = frame.shape[:2]

        # On sauvegarde le frame dans task
        self.is_waiting_for_human = True

        async def _run_hitl():
            try:
                # ETAPE 1: Auto-Guérison par API
                if self.ai_fallback:
                    logger.info("Tentative d'Auto-Guérison via l'API Vision (Arrière-plan)...")
                    temp_path = "temp_fallback.jpg"
                    cv2.imwrite(temp_path, frame)
                    boxes = await asyncio.to_thread(self.ai_fallback.ask_ai_with_fallbacks, temp_path, width, height)

                    if os.path.exists(temp_path):
                        os.remove(temp_path)

                    if boxes and len(boxes) > 0:
                        logger.info("Auto-Guérison API Réussie ! Le bot s'est adapaté.")
                        yolo_txt = self.ai_fallback.convert_to_yolo_format(boxes, width, height)
                        self._save_to_dataset(frame, yolo_txt)
                        self.is_waiting_for_human = False
                        return

                # SAVE ALWAYS IF API FAILS
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                debug_img_path = os.path.join("dataset", "needs_annotation", f"failed_{timestamp}.jpg")
                os.makedirs(os.path.dirname(debug_img_path), exist_ok=True)
                cv2.imwrite(debug_img_path, frame)
                logger.info(f"Image sauvegardée pour annotation manuelle dans {debug_img_path}")

                # ETAPE 2: Fallback Humain GUI
                logger.info("Auto-Guérison API échouée ou absente. Envoi de l'image à la GUI Operator.")
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
                self.intervention_event.clear()
            except Exception as e:
                logger.error(f"Erreur dans la tâche asynchrone HITL: {e}")
                self.is_waiting_for_human = False

        # Lance le process de décision en arrière plan pour ne pas bloquer le tracker poker
        asyncio.create_task(_run_hitl())

    def record_anomaly_silently(self, frame: np.ndarray, issue_type: str, reason: str):
        """
        Enregistre l'image pour un futur apprentissage, mais sans bloquer l'opérateur ni déclencher la GUI.
        Ceci est utile quand le bot parvient à se sauver lui-même (via son tracker ou solver) d'une erreur YOLO.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            debug_img_path = os.path.join("dataset", "needs_annotation", f"silently_failed_{timestamp}.jpg")
            os.makedirs(os.path.dirname(debug_img_path), exist_ok=True)
            cv2.imwrite(debug_img_path, frame)
            logger.info(f"Anomalie silencieuse ({issue_type}) : Image sauvegardée pour annotation dans {debug_img_path}")
        except Exception as e:
            logger.error(f"Erreur lors de la capture silencieuse: {e}")

    def record_shadow_failure(
        self,
        frame: np.ndarray,
        issue_type: str,
        reason: str,
        *,
        context: dict | None = None,
    ) -> None:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            image_path = self.shadow_dir / f"shadow_{timestamp}.jpg"
            manifest_record = {
                "timestamp": timestamp,
                "issue_type": str(issue_type or "unknown"),
                "reason": str(reason or ""),
                "context": dict(context or {}),
                "image_path": str(image_path),
            }
            if isinstance(frame, np.ndarray) and frame.size:
                cv2.imwrite(str(image_path), frame)
            with self.shadow_manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(manifest_record, ensure_ascii=True) + "\n")
            logger.info("Shadow failure capturee: %s", image_path)
        except Exception as e:
            logger.error(f"Erreur lors de la capture shadow mode: {e}")

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
