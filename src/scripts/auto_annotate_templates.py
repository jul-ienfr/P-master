import os
import cv2
import json
from pathlib import Path
import sys

# Define root
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.vision.detector import PokerDetector
from src.vision.yolo_schema import YOLO_CLASS_MAP, write_dataset_yaml

def create_annotations(dataset_name: str):
    print(f"\n--- Démarrage de l'Auto-Annotation (OpenCV -> YOLO) sur {dataset_name} ---")
    
    detector = PokerDetector()
    dataset_dir = ROOT / "dataset" / dataset_name
    img_dir = dataset_dir / "images"
    label_dir = dataset_dir / "labels"
    
    if not img_dir.exists():
        print(f"❌ Dossier introuvable: {img_dir}")
        return
        
    label_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    images = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))
    total_images = len(images)
    for img_path in images:
        print(f"[{count+1}/{total_images}] Analyse et detection des cartes sur {img_path.name}...")
        img = cv2.imread(str(img_path))
        if img is None: continue
        
        height, width = img.shape[:2]
        
        # 1. Utiliser le template OpenCV (Fallback) pour DETECTER
        state = detector.fallback_detector.analyze_frame(img)
        
        yolo_lines = []
        
        # 2. Convertir les détections OpenCV en Bboxes YOLO Normalizees
        def add_boxes(detections, class_name):
            if not isinstance(detections, list):
                detections = [detections] if detections else []
            for d in detections:
                if not d: continue
                opt_bbox = getattr(d, 'bbox', None)
                if not opt_bbox: continue
                x1, y1, x2, y2 = opt_bbox
                cls_id = YOLO_CLASS_MAP.get(class_name)
                
                # YOLO format: cls_id x_center y_center width height (Normalized 0.0-1.0)
                box_w = x2 - x1
                box_h = y2 - y1
                x_center = x1 + (box_w / 2)
                y_center = y1 + (box_h / 2)
                
                yolo_lines.append(f"{cls_id} {x_center/width:.6f} {y_center/height:.6f} {box_w/width:.6f} {box_h/height:.6f}")

        # Mapping de toutes les classes
        for card in state.board_cards:
            cls_name = card.class_name if card.class_name in YOLO_CLASS_MAP else "board_card"
            add_boxes([card], cls_name)
            
        for card in state.hero_cards:
            cls_name = card.class_name if card.class_name in YOLO_CLASS_MAP else "hero_card"
            add_boxes([card], cls_name)
            
        add_boxes(state.pots, "pot_area")
        add_boxes(state.stacks, "stack_area")
        add_boxes(state.player_names, "player_name_area")
        add_boxes([state.dealer_button] if state.dealer_button else [], "dealer_button")
        
        for btn in state.action_buttons:
            # Action buttons contain the specific label class "fold_button" etc. in detection.class_name
            add_boxes([btn], btn.class_name)

        # 3. Sauvegarde dans fichier YOLO .txt
        label_file = label_dir / (img_path.stem + ".txt")
        with open(label_file, "w") as f:
            f.write("\n".join(yolo_lines))
        count += 1
        
    print(f"✅ {count} images annotées avec succès dans {label_dir}")
    
    # 4. Generer dataset.yaml
    yaml_path = dataset_dir / "dataset.yaml"
    write_dataset_yaml(
        output_path=yaml_path,
        dataset_root=dataset_dir,
        train_images_dir=img_dir,
        val_images_dir=img_dir, # Use same for now since small dataset
    )
    print(f"✅ Fichier de configuration YOLO généré : {yaml_path}")
    print(f"👉 Tu peux maintenant lancer: python src/scripts/train_yolo.py --data dataset/{dataset_name}/dataset.yaml\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="PokerStars_NLHE_6Max", help="Nom du dossier dans dataset/")
    args = parser.parse_args()
    create_annotations(args.dataset)
