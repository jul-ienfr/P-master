import os
import base64
import json
import logging
import argparse
from openai import OpenAI
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AutoAnnotator")

CLASS_MAP = {
    "board_card": 0,
    "hero_card": 1,
    "pot_area": 2,
    "stack_area": 3,
    "dealer_button": 4
}

class AutoAnnotator:
    def __init__(self, providers: list):
        """
        Initialise l'annotateur avec une liste infinie de fournisseurs (Fallbacks en cascade).
        providers: [{'base_url': '...', 'model': '...', 'api_key': '...'}]
        """
        self.providers = providers
        if not self.providers:
            logger.warning("Aucun fournisseur d'IA configuré. Impossible d'annoter.")

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def ask_ai_with_fallbacks(self, image_path: str, width: int, height: int) -> list:
        """Boucle sur les fournisseurs jusqu'à trouver un résultat valide (Fallback)."""
        for i, provider in enumerate(self.providers):
            api_key = provider.get("api_key", "")
            base_url = provider.get("base_url", "")
            model = provider.get("model", "gpt-4o")
            
            # Formatage propre de l'URL
            if not base_url or base_url.strip() == "":
                base_url = None
                
            try:
                logger.info(f"Tentative {i+1}/{len(self.providers)} avec le modèle {model}...")
                client = OpenAI(api_key=api_key or "local", base_url=base_url)
                
                boxes = self._ask_single_ai(client, model, image_path, width, height)
                
                if boxes and len(boxes) > 0:
                    return boxes # Succès, on quitte la boucle
                else:
                    logger.warning(f"Le modèle {model} n'a rien détecté.")
                    
            except Exception as e:
                logger.error(f"Échec avec le fournisseur {model}: {e}")
                
        logger.error(f"Tous les fournisseurs ({len(self.providers)}) ont échoué sur {image_path}.")
        return []

    def _ask_single_ai(self, client: OpenAI, model: str, image_path: str, width: int, height: int) -> list:
        base64_image = self.encode_image(image_path)
        prompt = f"""
Tu es un expert en Computer Vision pour des tables de Poker.
L'image fournie fait {width}x{height} pixels.
Détecte les éléments suivants et retourne leurs Bounding Boxes au format JSON strict.
Les classes possibles sont : "board_card", "hero_card", "pot_area", "stack_area", "dealer_button".
Format attendu (réponds UNIQUEMENT avec ce JSON) :
{{
  "boxes": [
    {{"class": "board_card", "xmin": 200, "ymin": 300, "xmax": 250, "ymax": 380}}
  ]
}}
Si tu ne vois rien, retourne {{"boxes": []}}.
"""
        call_params = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "temperature": 0.0
        }
        
        if client.base_url and "openai" in (client.base_url.host or ""):
             call_params["response_format"] = { "type": "json_object" }

        response = client.chat.completions.create(**call_params)
        result_text = response.choices[0].message.content.strip()
        
        # Nettoyage Markdown (Groq / Ollama safe)
        if result_text.startswith("```json"): result_text = result_text[7:]
        if result_text.startswith("```"): result_text = result_text[3:]
        if result_text.endswith("```"): result_text = result_text[:-3]
            
        parsed = json.loads(result_text.strip())
        
        if isinstance(parsed, dict) and "boxes" in parsed:
            return parsed["boxes"]
        elif isinstance(parsed, dict):
            for key in parsed:
                if isinstance(parsed[key], list): return parsed[key]
        return parsed if isinstance(parsed, list) else []

    def convert_to_yolo_format(self, boxes: list, img_width: int, img_height: int) -> str:
        yolo_lines = []
        for box in boxes:
            cls_name = box.get("class")
            if cls_name not in CLASS_MAP: continue
            cls_id = CLASS_MAP[cls_name]
            try:
                xmin, ymin, xmax, ymax = float(box["xmin"]), float(box["ymin"]), float(box["xmax"]), float(box["ymax"])
            except (ValueError, TypeError, KeyError): continue

            abs_w, abs_h = xmax - xmin, ymax - ymin
            abs_x_center, abs_y_center = xmin + (abs_w / 2), ymin + (abs_h / 2)
            
            yolo_lines.append(f"{cls_id} {abs_x_center/img_width:.6f} {abs_y_center/img_height:.6f} {abs_w/img_width:.6f} {abs_h/img_height:.6f}")

        return "\n".join(yolo_lines)

    def process_dataset(self, raw_dir: str = "dataset/raw_images", labels_dir: str = "dataset/labels"):
        if not self.providers: return
        
        os.makedirs(labels_dir, exist_ok=True)
            
        for filename in os.listdir(raw_dir):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')): continue

            img_path = os.path.join(raw_dir, filename)
            label_path = os.path.join(labels_dir, os.path.splitext(filename)[0] + ".txt")

            if os.path.exists(label_path): continue # Déjà fait

            logger.info(f"Analyse de {filename}...")
            img = cv2.imread(img_path)
            if img is None: continue
            height, width = img.shape[:2]

            boxes = self.ask_ai_with_fallbacks(img_path, width, height)
            
            if boxes:
                with open(label_path, "w") as f:
                    f.write(self.convert_to_yolo_format(boxes, width, height))
                logger.info(f"✅ {len(boxes)} objets annotés sur {filename}.")
            else:
                logger.warning(f"❌ Échec total pour {filename}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers-json", type=str, default="", help="JSON string contenant la liste des fournisseurs")
    parser.add_argument("--raw-dir", type=str, default="dataset/raw_images")
    parser.add_argument("--labels-dir", type=str, default="dataset/labels")
    args = parser.parse_args()

    # Si on appelle le script depuis l'interface Tauri, il passera un JSON.
    providers = []
    if args.providers_json:
        try:
            providers = json.loads(args.providers_json)
        except json.JSONDecodeError:
            logger.error("JSON des fournisseurs invalide.")
    else:
        # Fallback pour usage terminal direct
        providers = [{
            "base_url": os.environ.get("OPENAI_BASE_URL", ""),
            "model": "gpt-4o",
            "api_key": os.environ.get("OPENAI_API_KEY", "")
        }]

    annotator = AutoAnnotator(providers=providers)
    annotator.process_dataset(raw_dir=args.raw_dir, labels_dir=args.labels_dir)
