import argparse
import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np
from openai import OpenAI

from src.vision.yolo_schema import YOLO_CLASS_MAP, YOLO_CLASS_NAMES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AutoAnnotator")

# --- Voie Djev vision (observer / fail-open, jamais d'enforcing) ---
# Ajout isolé ici : la boucle OpenAI/Groq de ``ask_ai_with_fallbacks`` est
# inchangée. La voie Djev est opt-in (défaut off) et, quand elle est active,
# elle reste un observateur pur : image -> LAN qwen2.5-vl-3b (loopback
# uniquement, clé via NOM de var d'env, jamais en dur), jugement/validation
# des bboxes -> Djev (schéma bbox+label+confiance, "not stated" si illisible,
# tous les calculs — aires, IoU, accords — en code, jamais demandés au
# modèle). Tout échec -> fail-open : les boxes d'origine sont retournées
# telles quelles, jamais d'exception vers l'appelant.
DJEV_NOT_STATED = "not stated"
DEFAULT_DJEV_VISION_MODE = "off"  # observer | off (enforcing interdit ici)
DEFAULT_DJEV_VISION_LAN_URL = "http://127.0.0.1:8080/v1"
DEFAULT_DJEV_VISION_LAN_MODEL = "qwen2.5-vl-3b"
DEFAULT_DJEV_VISION_LAN_KEY_ENV = "POKER_JEV_LAN_KEY"
DEFAULT_DJEV_VISION_TIMEOUT_S = 15.0
DEFAULT_DJEV_VISION_MIN_CONFIDENCE = 0.3
_DJEV_VISION_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_DJEV_VISION_IOU_MATCH = 0.5


@dataclass
class DjevVisionConfig:
    """Config voie Djev vision : observer/fail-open pur, défaut off.

    Priorité : ``overrides`` > env > fichier (``base``). Zéro clé en dur :
    seule la clé LAN est lue, via le NOM de variable ``lan_api_key_env``.
    """

    mode: str = DEFAULT_DJEV_VISION_MODE
    lan_url: str = DEFAULT_DJEV_VISION_LAN_URL
    lan_model: str = DEFAULT_DJEV_VISION_LAN_MODEL
    lan_api_key_env: str = DEFAULT_DJEV_VISION_LAN_KEY_ENV
    timeout_s: float = DEFAULT_DJEV_VISION_TIMEOUT_S
    min_confidence: float = DEFAULT_DJEV_VISION_MIN_CONFIDENCE
    offline_mode: bool = False
    djev_enabled: bool = True  # consultation texte Djev (System One) en 2e rideau

    @classmethod
    def from_env(
        cls,
        overrides: dict | None = None,
        base: dict | None = None,
    ) -> "DjevVisionConfig":
        cfg = cls()
        if isinstance(base, dict):
            for key in (
                "mode", "lan_url", "lan_model", "lan_api_key_env",
                "timeout_s", "min_confidence", "offline_mode",
                "djev_enabled",
            ):
                if base.get(key) not in (None, "") and hasattr(cfg, key):
                    setattr(cfg, key, base[key])
        env = os.environ
        if env.get("POKER_DJEV_VISION_MODE"):
            cfg.mode = str(env["POKER_DJEV_VISION_MODE"]).strip().lower()
        if env.get("POKER_DJEV_VISION_LAN_URL"):
            cfg.lan_url = str(env["POKER_DJEV_VISION_LAN_URL"]).rstrip("/")
        if env.get("POKER_DJEV_VISION_LAN_MODEL"):
            cfg.lan_model = str(env["POKER_DJEV_VISION_LAN_MODEL"]).strip()
        if env.get("POKER_DJEV_VISION_LAN_KEY_ENV"):
            cfg.lan_api_key_env = str(env["POKER_DJEV_VISION_LAN_KEY_ENV"]).strip()
        if env.get("POKER_DJEV_VISION_TIMEOUT_S"):
            try:
                cfg.timeout_s = float(env["POKER_DJEV_VISION_TIMEOUT_S"])
            except ValueError:
                pass
        if env.get("POKER_DJEV_VISION_MIN_CONFIDENCE"):
            try:
                cfg.min_confidence = float(env["POKER_DJEV_VISION_MIN_CONFIDENCE"])
            except ValueError:
                pass
        if env.get("POKER_OFFLINE_MODE"):
            cfg.offline_mode = (
                str(env["POKER_OFFLINE_MODE"]).strip().lower()
                in ("1", "true", "yes", "on")
            )
        if overrides:
            for key, value in overrides.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        if cfg.mode not in ("observer", "off"):
            logger.warning(
                "DJEV-VISION | unknown mode %r, falling back to off", cfg.mode
            )
            cfg.mode = "off"
        return cfg

    def is_enabled(self) -> bool:
        return self.mode == "observer"


def _is_djev_vision_loopback(url: Any) -> bool:
    """True si l'URL vise le loopback (127.0.0.1, localhost, ::1)."""
    try:
        s = str(url or "").strip()
        if not s:
            return False
        if "://" not in s:
            s = "//" + s
        host = (urlparse(s).hostname or "").strip().lower()
    except Exception:
        return False
    return host in _DJEV_VISION_LOOPBACK_HOSTS


def _djev_num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _djev_area(box: dict) -> float:
    try:
        w = float(box["xmax"]) - float(box["xmin"])
        h = float(box["ymax"]) - float(box["ymin"])
    except (TypeError, ValueError, KeyError):
        return 0.0
    return max(0.0, w) * max(0.0, h)


def _djev_iou(a: dict, b: dict) -> float:
    """IoU calculé en code (jamais demandé au modèle)."""
    try:
        ax0, ay0, ax1, ay1 = (float(a[k]) for k in ("xmin", "ymin", "xmax", "ymax"))
        bx0, by0, bx1, by1 = (float(b[k]) for k in ("xmin", "ymin", "xmax", "ymax"))
    except (TypeError, ValueError, KeyError):
        return 0.0
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0.0:
        return 0.0
    union = _djev_area(a) + _djev_area(b) - inter
    return inter / union if union > 0.0 else 0.0


def _djev_normalize_box(raw: Any) -> dict | None:
    """Normalise une bbox juge vers {class, xmin, ymin, xmax, ymax, confidence}.

    Schéma strict : bbox + label + confiance ; "not stated" si le label est
    illisible/absent. Les coordonnées non numériques ou inversées -> rejet.
    """
    if not isinstance(raw, dict):
        return None
    label = raw.get("class", raw.get("label", ""))
    if not isinstance(label, str) or not label.strip():
        label = DJEV_NOT_STATED
    try:
        xmin = float(raw["xmin"])
        ymin = float(raw["ymin"])
        xmax = float(raw["xmax"])
        ymax = float(raw["ymax"])
    except (TypeError, ValueError, KeyError):
        return None
    if not (xmax > xmin and ymax > ymin):
        return None
    confidence = _djev_num(raw.get("confidence", raw.get("conf")))
    return {
        "class": label.strip(),
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "confidence": confidence,
    }


def _djev_build_judge_prompt(width: int, height: int, boxes: list) -> str:
    class_list = ", ".join(f'"{name}"' for name in YOLO_CLASS_NAMES)
    lines = []
    for i, box in enumerate(boxes):
        try:
            lines.append(
                f"- #{i}: class={box.get('class')} "
                f"xmin={box.get('xmin')} ymin={box.get('ymin')} "
                f"xmax={box.get('xmax')} ymax={box.get('ymax')} "
                f"(image {width}x{height})"
            )
        except (AttributeError, TypeError):
            continue
    proposed = "\n".join(lines) or "(none)"
    return f"""
Tu es un juge de validation de bounding boxes pour des tables de Poker.
L'image fournie fait {width}x{height} pixels. Voici les boxes proposees :
{proposed}
Les classes possibles sont : {class_list}.
Pour CHAQUE box proposee, reponds avec son label corrige et ta confiance
(float 0..1). Si un objet est illisible ou absent, label "{DJEV_NOT_STATED}".
Ne calcule AUCUNE aire ni IoU, retourne uniquement le jugement brut.
Format attendu (reponds UNIQUEMENT avec ce JSON) :
{{
  "judgements": [
    {{"index": 0, "class": "board_card", "xmin": 200, "ymin": 300, "xmax": 250, "ymax": 380, "confidence": 0.9}}
  ]
}}
Si rien n'est lisible, retourne {{"judgements": []}}.
"""


def _djev_query_lan_judge(
    base64_image: str,
    width: int,
    height: int,
    boxes: list,
    *,
    config: "DjevVisionConfig",
) -> list:
    """Image -> LAN qwen2.5-vl-3b (loopback), jugement brut des bboxes.

    Fail-open : tout échec -> liste vide (l'appelant garde les boxes
    d'origine). Zéro appel réseau si URL non-loopback ou offline_mode + WAN.
    """
    if not _is_djev_vision_loopback(config.lan_url):
        logger.warning(
            "DJEV-VISION | non-loopback lan_url %r refused (fail-open), "
            "boxes kept as-is",
            config.lan_url,
        )
        return []
    if config.offline_mode and not _is_djev_vision_loopback(config.lan_url):
        return []
    api_key = ""
    if config.lan_api_key_env:
        api_key = str(os.environ.get(config.lan_api_key_env, "") or "")
    try:
        client = OpenAI(
            api_key=api_key or "local",
            base_url=config.lan_url,
            max_retries=0,
            timeout=config.timeout_s,
        )
        response = client.chat.completions.create(
            model=config.lan_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": _djev_build_judge_prompt(width, height, boxes)},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            temperature=0.0,
        )
        result_text = str(
            response.choices[0].message.content or ""
        ).strip()
    except Exception as exc:  # timeout, connexion, LAN down -> fail-open
        logger.warning("DJEV-VISION | LAN judge unavailable (%s), boxes kept", type(exc).__name__)
        return []
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
    try:
        parsed = json.loads(result_text.strip())
    except (json.JSONDecodeError, ValueError):
        logger.warning("DJEV-VISION | malformed judge response, boxes kept")
        return []
    raw_list: list = []
    if isinstance(parsed, dict) and isinstance(parsed.get("judgements"), list):
        raw_list = parsed["judgements"]
    elif isinstance(parsed, dict):
        for key in parsed:
            if isinstance(parsed[key], list):
                raw_list = parsed[key]
                break
    elif isinstance(parsed, list):
        raw_list = parsed
    judged: list = []
    for raw in raw_list:
        box = _djev_normalize_box(raw)
        if box is None:
            continue
        if isinstance(raw, dict) and raw.get("index") not in (None, ""):
            try:
                box["index"] = int(raw["index"])
            except (TypeError, ValueError):
                pass
        judged.append(box)
    return judged


def djev_observe_boxes(
    boxes: list,
    base64_image: str,
    width: int,
    height: int,
    *,
    config: "DjevVisionConfig | None" = None,
) -> tuple[list, dict]:
    """Valide des bboxes via Djev en observer pur (jamais d'enforcing).

    Retourne ``(boxes_out, report)`` où ``boxes_out`` = boxes filtrées par
    accord géométrique (IoU calculé en code) + confiance, et ``report`` porte
    ``agree/disagree/fail-open`` pour le log. Mode off ou tout échec ->
    ``(boxes, {"status": "fail-open", ...})`` : les boxes d'origine sont
    gardées telles quelles.
    """
    cfg = config or DjevVisionConfig.from_env()
    started_boxes = list(boxes or [])
    if not cfg.is_enabled():
        return started_boxes, {"status": "off", "mode": cfg.mode}
    judged = _djev_query_lan_judge(
        base64_image, width, height, started_boxes, config=cfg
    )
    if not judged:
        return started_boxes, {
            "status": "fail-open",
            "reason": "no judgement (LAN down, refused, or malformed)",
            "kept": len(started_boxes),
        }
    kept: list = []
    agreed = 0
    for i, orig in enumerate(started_boxes):
        if not isinstance(orig, dict):
            continue
        best = None
        best_iou = 0.0
        for cand in judged:
            if cand.get("class") == DJEV_NOT_STATED:
                continue
            if cand.get("class") != orig.get("class"):
                continue
            idx = cand.get("index")
            if idx is not None and idx != i:
                continue
            iou = _djev_iou(orig, cand)
            if iou > best_iou:
                best_iou = iou
                best = cand
        conf = _djev_num(best.get("confidence")) if best else None
        if best is not None and best_iou >= _DJEV_VISION_IOU_MATCH and (
            conf is None or conf >= cfg.min_confidence
        ):
            agreed += 1
            kept.append(orig)
    report = {
        "status": f"observer ({'agree' if agreed else 'disagree'})",
        "proposed": len(started_boxes),
        "judged": len(judged),
        "agreed": agreed,
        "kept": len(kept),
        "iou_match": _DJEV_VISION_IOU_MATCH,
        "min_confidence": cfg.min_confidence,
    }
    logger.info(
        "DJEV-VISION | observer %s: %d/%d boxes kept (IoU>=%.2f, conf>=%.2f)",
        "agree" if agreed else "disagree",
        len(kept),
        len(started_boxes),
        _DJEV_VISION_IOU_MATCH,
        cfg.min_confidence,
    )
    return kept, report


class AutoAnnotator:
    def __init__(self, providers: list, djev_vision: "DjevVisionConfig | None" = None):
        """
        Initialise l'annotateur avec une liste infinie de fournisseurs (Fallbacks en cascade).
        providers: [{'base_url': '...', 'model': '...', 'api_key': '...'}]
        djev_vision: config voie Djev observer (défaut off, fail-open).
        """
        self.providers = providers
        self.djev_vision = djev_vision or DjevVisionConfig.from_env()
        if not self.providers:
            logger.warning("Aucun fournisseur d'IA configuré. Impossible d'annoter.")

    @staticmethod
    def _is_local_base_url(base_url: str | None) -> bool:
        if not base_url:
            return False
        lowered = str(base_url).strip().lower()
        return "127.0.0.1" in lowered or "localhost" in lowered

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def encode_image_frame(self, frame: np.ndarray) -> str:
        _, buffer = cv2.imencode(".jpg", frame)
        return base64.b64encode(buffer).decode("utf-8")

    def _has_any_usable_provider(self) -> bool:
        for provider in self.providers:
            api_key = str(provider.get("api_key", "") or "").strip()
            base_url = str(provider.get("base_url", "") or "").strip()
            if api_key or self._is_local_base_url(base_url or None):
                return True
        return False

    def ask_ai_with_fallbacks(
        self, image_path: str, width: int, height: int, frame: np.ndarray = None
    ) -> list:
        """Boucle sur les fournisseurs jusqu'à trouver un résultat valide (Fallback).

        La boucle OpenAI/Groq ci-dessous est INCHANGÉE. La voie Djev, quand elle
        est activée (mode observer), n'est qu'un 2e rideau : elle observe les
        boxes du 1er rideau et ne fait que filtrer par accord (IoU + confiance
        calculés en code). Jamais d'exception, jamais d'enforcing : tout échec
        -> boxes du 1er rideau gardées telles quelles.
        """
        boxes: list = []
        if not self._has_any_usable_provider():
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "AutoAnnotator disabled — no provider keys configured (%d remote providers), skipping LLM fallback on %s.",
                    len(self.providers),
                    image_path,
                )
            else:
                logger.info(
                    "AutoAnnotator disabled — no provider keys configured, skipping LLM fallback."
                )
        else:
            for i, provider in enumerate(self.providers):
                api_key = provider.get("api_key", "")
                base_url = provider.get("base_url", "")
                model = provider.get("model", "gpt-4o")

                # Formatage propre de l'URL
                if not base_url or base_url.strip() == "":
                    base_url = None

                if not api_key and not self._is_local_base_url(base_url):
                    logger.warning(
                        "Fournisseur %s ignoré: aucune clé API configurée pour la cible distante %s.",
                        model,
                        base_url or "default_openai",
                    )
                    continue

                try:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Tentative %d/%d avec le modèle %s...", i + 1, len(self.providers), model
                        )
                    else:
                        logger.info(
                            f"Tentative {i + 1}/{len(self.providers)} avec le modèle {model}..."
                        )
                    client = OpenAI(
                        api_key=api_key or "local",
                        base_url=base_url,
                        max_retries=0,
                    )

                    boxes = self._ask_single_ai(client, model, image_path, width, height, frame=frame)

                    if boxes and len(boxes) > 0:
                        break  # Succès, on quitte la boucle
                    else:
                        logger.warning(f"Le modèle {model} n'a rien détecté.")

                except Exception as e:
                    logger.error(f"Échec avec le fournisseur {model}: {e}")

            if not boxes:
                logger.error(f"Tous les fournisseurs ({len(self.providers)}) ont échoué sur {image_path}.")
                return []
        # --- Voie Djev observer (opt-in, défaut off, fail-open) ---
        try:
            if boxes and self.djev_vision.is_enabled():
                if frame is not None:
                    base64_image = self.encode_image_frame(frame)
                else:
                    base64_image = self.encode_image(image_path)
                observed, report = djev_observe_boxes(
                    boxes, base64_image, width, height, config=self.djev_vision
                )
                logger.info("DJEV-VISION | report=%s", report)
                return observed
        except Exception as exc:  # jamais d'exception vers l'appelant
            logger.warning(
                "DJEV-VISION | observer failed (%s), boxes kept",
                type(exc).__name__,
            )
        return boxes

    def _ask_single_ai(
        self,
        client: OpenAI,
        model: str,
        image_path: str,
        width: int,
        height: int,
        frame: np.ndarray = None,
    ) -> list:
        if frame is not None:
            base64_image = self.encode_image_frame(frame)
        else:
            base64_image = self.encode_image(image_path)

        class_list = ", ".join(f'"{name}"' for name in YOLO_CLASS_NAMES)
        prompt = f"""
Tu es un expert en Computer Vision pour des tables de Poker.
L'image fournie fait {width}x{height} pixels.
Détecte les éléments suivants et retourne leurs Bounding Boxes au format JSON strict.
Les classes possibles sont : {class_list}.
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
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ],
                }
            ],
            "temperature": 0.0,
        }

        if client.base_url and "openai" in (client.base_url.host or ""):
            call_params["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**call_params)
        result_text = response.choices[0].message.content.strip()

        # Nettoyage Markdown (Groq / Ollama safe)
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]

        parsed = json.loads(result_text.strip())

        if isinstance(parsed, dict) and "boxes" in parsed:
            return parsed["boxes"]
        elif isinstance(parsed, dict):
            for key in parsed:
                if isinstance(parsed[key], list):
                    return parsed[key]
        return parsed if isinstance(parsed, list) else []

    def convert_to_yolo_format(self, boxes: list, img_width: int, img_height: int) -> str:
        yolo_lines = []
        for box in boxes:
            cls_name = box.get("class")
            if cls_name not in YOLO_CLASS_MAP:
                continue
            cls_id = YOLO_CLASS_MAP[cls_name]
            try:
                xmin, ymin, xmax, ymax = (
                    float(box["xmin"]),
                    float(box["ymin"]),
                    float(box["xmax"]),
                    float(box["ymax"]),
                )
            except (ValueError, TypeError, KeyError):
                continue

            abs_w, abs_h = xmax - xmin, ymax - ymin
            abs_x_center, abs_y_center = xmin + (abs_w / 2), ymin + (abs_h / 2)

            yolo_lines.append(
                f"{cls_id} {abs_x_center / img_width:.6f} {abs_y_center / img_height:.6f} {abs_w / img_width:.6f} {abs_h / img_height:.6f}"
            )

        return "\n".join(yolo_lines)

    def process_dataset(
        self, raw_dir: str = "dataset/raw_images", labels_dir: str = "dataset/labels"
    ):
        if not self.providers:
            return

        os.makedirs(labels_dir, exist_ok=True)

        for filename in os.listdir(raw_dir):
            if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue

            img_path = os.path.join(raw_dir, filename)
            label_path = os.path.join(labels_dir, os.path.splitext(filename)[0] + ".txt")

            if os.path.exists(label_path):
                continue  # Déjà fait

            logger.info(f"Analyse de {filename}...")
            img = cv2.imread(img_path)
            if img is None:
                continue
            height, width = img.shape[:2]

            boxes = self.ask_ai_with_fallbacks(img_path, width, height)

            if boxes:
                with open(label_path, "w") as f:
                    f.write(self.convert_to_yolo_format(boxes, width, height))
                logger.info(f"✅ {len(boxes)} objets annotés sur {filename}.")
            else:
                logger.warning(f"❌ Échec total pour {filename}.")


def _djev_base_from_config_file(path: str) -> dict | None:
    """Lit le bloc fichier ``auto_annotator.djev_vision`` (base, défaut off)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    node = data.get("auto_annotator") if isinstance(data, dict) else None
    if isinstance(node, dict) and isinstance(node.get("djev_vision"), dict):
        return dict(node["djev_vision"])
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--providers-json",
        type=str,
        default="",
        help="JSON string contenant la liste des fournisseurs",
    )
    parser.add_argument("--raw-dir", type=str, default="dataset/raw_images")
    parser.add_argument("--labels-dir", type=str, default="dataset/labels")
    parser.add_argument(
        "--djev-vision-mode",
        type=str,
        default="",
        help="Voie Djev observer : 'observer' (opt-in) ou 'off' (défaut).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="Chemin config.json (bloc auto_annotator.djev_vision lu comme base).",
    )
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
        providers = [
            {
                "base_url": os.environ.get("OPENAI_BASE_URL", ""),
                "model": "gpt-4o",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
            }
        ]

    overrides: dict = {}
    if str(args.djev_vision_mode or "").strip():
        overrides["mode"] = str(args.djev_vision_mode).strip().lower()
    djev_base = _djev_base_from_config_file(
        args.config or os.environ.get("POKER_CONFIG", "config.json")
    )
    djev_cfg = DjevVisionConfig.from_env(overrides or None, base=djev_base)
    annotator = AutoAnnotator(providers=providers, djev_vision=djev_cfg)
    annotator.process_dataset(raw_dir=args.raw_dir, labels_dir=args.labels_dir)
