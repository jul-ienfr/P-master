import logging
import os
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from src.runtime.player_name_resolver import (
    is_placeholder_player_name,
    is_probable_ui_name,
    is_usable_player_name,
    sanitize_player_name,
)

try:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="urllib3 .* doesn't match a supported version!",
        )
        from surya.common.surya.schema import TaskNames
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor

    SURYA_AVAILABLE = True
except ImportError:
    SURYA_AVAILABLE = False

try:
    from rapidocr import RapidOCR

    RAPIDOCR_AVAILABLE = True
except ImportError:
    RapidOCR = None
    RAPIDOCR_AVAILABLE = False

try:
    from rapidocr import EngineType, LangRec, ModelType, OCRVersion

    RAPIDOCR_V5_CONFIG_AVAILABLE = True
except ImportError:
    EngineType = None
    LangRec = None
    ModelType = None
    OCRVersion = None
    RAPIDOCR_V5_CONFIG_AVAILABLE = False

try:
    from doctr.models import ocr_predictor

    DOCTR_AVAILABLE = True
except ImportError:
    DOCTR_AVAILABLE = False

try:
    import pytesseract

    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import easyocr

    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

logger = logging.getLogger(__name__)

SUPPORTED_OCR_ENGINES = ("rapidocr", "easyocr", "tesseract", "surya", "doctr")
SUPPORTED_OCR_MODES = ("priority", "fallback", "consensus_amounts")
DEFAULT_AMOUNT_THOUSANDS_SEPARATORS = (" ",)
DEFAULT_AMOUNT_DECIMAL_SEPARATORS: Tuple[str, ...] = ()


def _configure_tesseract_binary() -> None:
    if not TESSERACT_AVAILABLE:
        return

    existing = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or "").strip()
    if existing and Path(existing).is_file():
        return

    env_candidate = str(os.getenv("TESSERACT_CMD") or "").strip()
    candidates = [
        env_candidate,
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files\NAPS2\lib\_win64\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


_configure_tesseract_binary()


@dataclass
class OCRTextCandidate:
    engine: str
    text: str
    variant: str = "original"


@dataclass
class OCRAmountCandidate:
    engine: str
    raw_text: str
    value: Optional[float]


class BaseOCREngine:
    name = "base"

    def read_text(self, image_crop: np.ndarray) -> str:
        raise NotImplementedError


class RapidOCREngine(BaseOCREngine):
    name = "rapidocr"
    _init_lock = Lock()
    _predict_lock = Lock()
    _engine: Optional["RapidOCR"] = None
    _load_error: Optional[str] = None

    def __init__(self):
        if not RAPIDOCR_AVAILABLE:
            raise RuntimeError("rapidocr is not installed")

    @staticmethod
    def _extract_text(result: object) -> str:
        texts = getattr(result, "txts", None) or ()
        if texts:
            return " ".join(part.strip() for part in texts if isinstance(part, str) and part.strip()).strip()

        if isinstance(result, dict):
            candidate_text = result.get("txt") or result.get("text")
            if isinstance(candidate_text, str) and candidate_text.strip():
                return candidate_text.strip()
            return ""

        if isinstance(result, (list, tuple)):
            collected: List[str] = []
            for item in result:
                if isinstance(item, str):
                    if item.strip():
                        collected.append(item.strip())
                    continue
                nested_text = RapidOCREngine._extract_text(item)
                if nested_text:
                    collected.append(nested_text)
                    continue
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    candidate_text = item[1]
                    if isinstance(candidate_text, str) and candidate_text.strip():
                        collected.append(candidate_text.strip())
            return " ".join(collected).strip()

        return ""

    @classmethod
    def _build_engine(cls) -> "RapidOCR":
        if not RAPIDOCR_V5_CONFIG_AVAILABLE:
            return RapidOCR()

        return RapidOCR(
            params={
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.EN,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
            }
        )

    @classmethod
    def _get_engine(cls) -> "RapidOCR":
        if cls._engine is not None:
            return cls._engine

        if cls._load_error is not None:
            raise RuntimeError(cls._load_error)

        with cls._init_lock:
            if cls._engine is not None:
                return cls._engine
            if cls._load_error is not None:
                raise RuntimeError(cls._load_error)

            try:
                cls._engine = cls._build_engine()
            except Exception as exc:
                if RAPIDOCR_V5_CONFIG_AVAILABLE:
                    logger.warning(
                        "RapidOCR PP-OCRv5 initialization failed, falling back to RapidOCR defaults: %s",
                        exc,
                    )
                    try:
                        cls._engine = RapidOCR()
                        return cls._engine
                    except Exception as fallback_exc:
                        cls._load_error = f"rapidocr initialization failed: {fallback_exc}"
                        raise RuntimeError(cls._load_error) from fallback_exc
                cls._load_error = f"rapidocr initialization failed: {exc}"
                raise RuntimeError(cls._load_error) from exc

        return cls._engine

    @staticmethod
    def _preprocess_for_ocr(image_crop: np.ndarray) -> np.ndarray:
        if image_crop.shape[0] < 5 or image_crop.shape[1] < 5:
            return image_crop
        # Upscale x3 for better font recognition
        enlarged = cv2.resize(image_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        # Grayscale then convert back to RGB shape
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    def read_text(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        engine = self._get_engine()
        
        # Apply OpenCV Preprocessing
        enhanced_image = self._preprocess_for_ocr(image_crop)
        pil_image = Image.fromarray(enhanced_image)

        with self._predict_lock:
            result = engine(pil_image, use_det=False, use_cls=False, use_rec=True)

        return self._extract_text(result)


class SuryaEngine(BaseOCREngine):
    name = "surya"
    _init_lock = Lock()
    _predict_lock = Lock()
    _recognition_predictor: Optional["RecognitionPredictor"] = None
    _load_error: Optional[str] = None

    def __init__(self):
        if not SURYA_AVAILABLE:
            raise RuntimeError("surya-ocr is not installed")

    @classmethod
    def _get_predictor(cls) -> "RecognitionPredictor":
        if cls._recognition_predictor is not None:
            return cls._recognition_predictor

        if cls._load_error is not None:
            raise RuntimeError(cls._load_error)

        with cls._init_lock:
            if cls._recognition_predictor is not None:
                return cls._recognition_predictor
            if cls._load_error is not None:
                raise RuntimeError(cls._load_error)

            try:
                foundation_predictor = FoundationPredictor()
                recognition_predictor = RecognitionPredictor(foundation_predictor)
                recognition_predictor.disable_tqdm = True
                cls._recognition_predictor = recognition_predictor
            except Exception as exc:
                cls._load_error = f"surya initialization failed: {exc}"
                raise RuntimeError(cls._load_error) from exc

        return cls._recognition_predictor

    def read_text(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        predictor = self._get_predictor()
        rgb_image = cv2.cvtColor(image_crop, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_image)
        width, height = pil_image.size
        bboxes = [[[0, 0, width, height]]]

        with self._predict_lock:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="'pin_memory' argument is set as true but no accelerator is found.*",
                )
                predictions = predictor(
                    [pil_image],
                    task_names=[TaskNames.ocr_without_boxes],
                    bboxes=bboxes,
                    math_mode=False,
                )

        if not predictions:
            return ""

        return " ".join(
            line.text.strip()
            for line in predictions[0].text_lines
            if getattr(line, "text", "").strip()
        ).strip()


class DocTREngine(BaseOCREngine):
    name = "doctr"

    def __init__(self):
        self.predictor = None
        if not DOCTR_AVAILABLE:
            raise RuntimeError("python-doctr is not installed")

        self.predictor = ocr_predictor(pretrained=True, assume_straight_pages=True)

    def read_text(self, image_crop: np.ndarray) -> str:
        if self.predictor is None or image_crop is None or image_crop.size == 0:
            return ""

        rgb_image = cv2.cvtColor(image_crop, cv2.COLOR_BGR2RGB)
        result = self.predictor([rgb_image])
        extracted_words: List[str] = []
        for block in result.pages[0].blocks:
            for line in block.lines:
                for word in line.words:
                    extracted_words.append(word.value)
        return " ".join(extracted_words)


class TesseractEngine(BaseOCREngine):
    name = "tesseract"

    def __init__(self):
        if not TESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract is not installed")
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise RuntimeError(f"tesseract binary is not available: {exc}") from exc

    def read_text(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
        normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        text = pytesseract.image_to_string(normalized, config="--psm 7")
        return text.strip()


class EasyOCREngine(BaseOCREngine):
    name = "easyocr"

    def __init__(self):
        if not EASYOCR_AVAILABLE:
            raise RuntimeError("easyocr is not installed")
        self.reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    def read_text(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        rgb_image = cv2.cvtColor(image_crop, cv2.COLOR_BGR2RGB)
        result = self.reader.readtext(rgb_image, detail=0, paragraph=False)
        return " ".join(part.strip() for part in result if isinstance(part, str)).strip()


class PokerOCR:
    def __init__(
        self,
        use_gpu: bool = True,
        enabled_engines: Optional[Sequence[str]] = None,
        mode: str = "consensus_amounts",
        parallel: bool = True,
        allow_decimal_amounts: bool = False,
        amount_thousands_separators: Optional[Sequence[str]] = None,
        amount_decimal_separators: Optional[Sequence[str]] = None,
    ):
        del use_gpu
        self.mode = mode if mode in SUPPORTED_OCR_MODES else "consensus_amounts"
        self.parallel = bool(parallel)
        self.allow_decimal_amounts = bool(allow_decimal_amounts)
        self.amount_thousands_separators = self._normalize_amount_separators(
            amount_thousands_separators,
            default=DEFAULT_AMOUNT_THOUSANDS_SEPARATORS,
        )
        default_decimal_separators = (".", ",") if self.allow_decimal_amounts else DEFAULT_AMOUNT_DECIMAL_SEPARATORS
        self.amount_decimal_separators = self._normalize_amount_separators(
            amount_decimal_separators,
            default=default_decimal_separators,
            allow_empty=True,
        )
        if not self.allow_decimal_amounts:
            self.amount_decimal_separators = ()
        self.enabled_engines = self._normalize_engines(enabled_engines)
        self.engines: List[BaseOCREngine] = []
        self.last_metadata: Dict[str, object] = self._empty_metadata()
        self._load_engines()

    @classmethod
    def from_config(cls, config: Optional[dict]):
        cfg = config or {}
        amount_cfg = cfg.get("amount_format", {})
        if not isinstance(amount_cfg, dict):
            amount_cfg = {}
        return cls(
            use_gpu=bool(cfg.get("use_gpu", True)),
            enabled_engines=cfg.get("enabled_engines"),
            mode=str(cfg.get("mode", cfg.get("merge_strategy", "consensus_amounts")) or "consensus_amounts"),
            parallel=bool(cfg.get("parallel", True)),
            allow_decimal_amounts=bool(amount_cfg.get("allow_decimals", cfg.get("allow_decimal_amounts", False))),
            amount_thousands_separators=amount_cfg.get("thousands_separators"),
            amount_decimal_separators=amount_cfg.get("decimal_separators"),
        )

    def _normalize_engines(self, enabled_engines: Optional[Sequence[str]]) -> List[str]:
        requested = list(enabled_engines or self._default_requested_engines())
        normalized: List[str] = []
        for engine in requested:
            key = str(engine).strip().lower()
            if key in SUPPORTED_OCR_ENGINES and key not in normalized:
                normalized.append(key)
        return normalized or self._default_requested_engines()

    @staticmethod
    def _default_requested_engines() -> List[str]:
        preferred: List[str] = []
        if RAPIDOCR_AVAILABLE:
            preferred.append("rapidocr")
        if EASYOCR_AVAILABLE:
            preferred.append("easyocr")
        if TESSERACT_AVAILABLE:
            preferred.append("tesseract")
        if preferred:
            return preferred

        legacy: List[str] = []
        if SURYA_AVAILABLE:
            legacy.append("surya")
        if DOCTR_AVAILABLE:
            legacy.append("doctr")
        return legacy or ["rapidocr", "easyocr", "tesseract", "surya", "doctr"]

    def _load_engines(self) -> None:
        engine_factories = {
            "rapidocr": RapidOCREngine,
            "surya": SuryaEngine,
            "doctr": DocTREngine,
            "tesseract": TesseractEngine,
            "easyocr": EasyOCREngine,
        }
        available: List[BaseOCREngine] = []
        unavailable: Dict[str, str] = {}

        for engine_name in self.enabled_engines:
            factory = engine_factories.get(engine_name)
            if factory is None:
                unavailable[engine_name] = "unsupported"
                continue
            try:
                available.append(factory())
                logger.info("OCR engine '%s' loaded successfully.", engine_name)
            except Exception as exc:
                unavailable[engine_name] = str(exc)
                logger.warning("OCR engine '%s' unavailable: %s", engine_name, exc)

        self.engines = available
        self.last_metadata = {
            **self._empty_metadata(),
            "requested_engines": list(self.enabled_engines),
            "loaded_engines": [engine.name for engine in self.engines],
            "unavailable_engines": unavailable,
            "mode": self.mode,
            "parallel": self.parallel,
            "allow_decimal_amounts": self.allow_decimal_amounts,
            "amount_thousands_separators": list(self.amount_thousands_separators),
            "amount_decimal_separators": list(self.amount_decimal_separators),
        }

    @staticmethod
    def _empty_metadata() -> Dict[str, object]:
        return {
            "field": "",
            "mode": "consensus_amounts",
            "parallel": True,
            "allow_decimal_amounts": False,
            "amount_thousands_separators": list(DEFAULT_AMOUNT_THOUSANDS_SEPARATORS),
            "amount_decimal_separators": list(DEFAULT_AMOUNT_DECIMAL_SEPARATORS),
            "supported_engines": list(SUPPORTED_OCR_ENGINES),
            "requested_engines": [],
            "loaded_engines": [],
            "unavailable_engines": {},
            "selected_engine": "",
            "selected_text": "",
            "selected_variant": "",
            "selected_amount": None,
            "selected_confidence": 0.0,
            "engine_scores": {},
            "candidates": [],
            "agreement": "none",
        }

    def get_metadata(self) -> Dict[str, object]:
        return dict(self.last_metadata)

    @staticmethod
    def _normalize_amount_separators(
        separators: Optional[Sequence[str]],
        *,
        default: Sequence[str],
        allow_empty: bool = False,
    ) -> Tuple[str, ...]:
        if separators is None:
            return tuple(default)

        raw_values: Sequence[str]
        if isinstance(separators, str):
            raw_values = [separators]
        else:
            raw_values = separators

        normalized: List[str] = []
        aliases = {
            "space": " ",
            "spaces": " ",
            "nbsp": " ",
            "nonbreaking_space": " ",
        }
        allowed = {" ", ".", ","}
        for raw_value in raw_values:
            if raw_value is None:
                continue
            candidate = str(raw_value).replace("\u00A0", " ")
            alias = aliases.get(candidate.strip().lower())
            separator = alias if alias is not None else candidate
            if separator not in allowed or separator in normalized:
                continue
            normalized.append(separator)

        if normalized:
            return tuple(normalized)
        return () if allow_empty else tuple(default)

    @staticmethod
    def _normalize_amount_token(token: str) -> str:
        token = token.replace("\u00A0", " ")
        token = token.strip(" -.,")
        token = token.replace("-", "")
        token = re.sub(r"\s+", " ", token)
        corrections = {"O": "0", "S": "5", "I": "1", "L": "1", "B": "8"}
        return "".join(corrections.get(char, char) for char in token)

    @staticmethod
    def _parse_integer_candidate(token: str, thousands_separators: Sequence[str]) -> Optional[float]:
        if not token:
            return None

        allowed_separators = {separator for separator in thousands_separators if separator}
        if any(not (char.isdigit() or char in allowed_separators) for char in token):
            return None

        sanitized = token
        for separator in allowed_separators:
            sanitized = sanitized.replace(separator, "")

        if not sanitized.isdigit():
            return None
        return float(sanitized)

    @classmethod
    def _parse_decimal_candidate(
        cls,
        token: str,
        thousands_separators: Sequence[str],
        decimal_separators: Sequence[str],
    ) -> Optional[float]:
        if not token:
            return None

        allowed_separators = {separator for separator in thousands_separators if separator}
        allowed_separators.update(separator for separator in decimal_separators if separator)
        if any(not (char.isdigit() or char in allowed_separators) for char in token):
            return None

        matched_decimal_separators = [separator for separator in decimal_separators if separator and separator in token]
        if len(matched_decimal_separators) > 1:
            return None

        decimal_separator = matched_decimal_separators[0] if matched_decimal_separators else ""
        if decimal_separator:
            if token.count(decimal_separator) != 1:
                return None
            integer_part, fractional_part = token.rsplit(decimal_separator, 1)
            if not integer_part or not fractional_part or not fractional_part.isdigit():
                return None
            if len(fractional_part) > 2:
                return None
            if any(separator and separator in fractional_part for separator in thousands_separators):
                return None
        else:
            integer_part = token
            fractional_part = ""

        integer_value = cls._parse_integer_candidate(integer_part, thousands_separators)
        if integer_value is None:
            return None
        if not decimal_separator:
            return integer_value

        try:
            return float(f"{int(integer_value)}.{fractional_part}")
        except ValueError:
            return None

    @classmethod
    def _parse_amount_with_format(
        cls,
        raw_text: str,
        *,
        allow_decimal_amounts: bool,
        thousands_separators: Sequence[str],
        decimal_separators: Sequence[str],
    ) -> Optional[float]:
        if not raw_text:
            return None

        normalized = raw_text.upper().strip().replace("\u00A0", " ")
        normalized = normalized.replace("$", " ").replace("€", " ").replace("BB", " ")
        candidates = list(re.finditer(r"(?<![0-9A-Z])[0-9OSILB][0-9OSILB\s,.\-]*[KM]?", normalized))
        if not candidates:
            return None

        def normalize_candidate(candidate_text: str) -> Optional[float]:
            multiplier = 1.0
            if candidate_text.endswith("K"):
                multiplier = 1000.0
                candidate_text = candidate_text[:-1]
            elif candidate_text.endswith("M"):
                multiplier = 1000000.0
                candidate_text = candidate_text[:-1]

            # Reject bare OCR-confusable letters to avoid inventing numbers from UI text.
            if not any(char.isdigit() for char in candidate_text):
                return None

            cleaned = cls._normalize_amount_token(candidate_text)
            if not any(char.isdigit() for char in cleaned):
                return None

            if allow_decimal_amounts:
                parsed_value = cls._parse_decimal_candidate(cleaned, thousands_separators, decimal_separators)
            else:
                parsed_value = cls._parse_integer_candidate(cleaned, thousands_separators)

            if parsed_value is None:
                return None
            return parsed_value * multiplier

        normalized_candidates: List[Tuple[int, float]] = []
        for match in candidates:
            parsed_value = normalize_candidate(match.group(0))
            if parsed_value is None:
                continue
            digit_count = sum(char.isdigit() for char in match.group(0))
            normalized_candidates.append((digit_count, parsed_value))

        if not normalized_candidates:
            return None

        _, best_val = max(normalized_candidates, key=lambda item: item[0])
        return best_val

    @classmethod
    def parse_amount(
        cls,
        raw_text: str,
        *,
        allow_decimal_amounts: bool = False,
        thousands_separators: Optional[Sequence[str]] = None,
        decimal_separators: Optional[Sequence[str]] = None,
    ) -> Optional[float]:
        normalized_thousands = cls._normalize_amount_separators(
            thousands_separators,
            default=DEFAULT_AMOUNT_THOUSANDS_SEPARATORS,
        )
        normalized_decimals = ()
        if allow_decimal_amounts:
            normalized_decimals = cls._normalize_amount_separators(
                decimal_separators,
                default=(".", ","),
                allow_empty=True,
            )

        return cls._parse_amount_with_format(
            raw_text,
            allow_decimal_amounts=allow_decimal_amounts,
            thousands_separators=normalized_thousands,
            decimal_separators=normalized_decimals,
        )

    def _parse_amount_with_current_format(self, raw_text: str) -> Optional[float]:
        return self._parse_amount_with_format(
            raw_text,
            allow_decimal_amounts=self.allow_decimal_amounts,
            thousands_separators=self.amount_thousands_separators,
            decimal_separators=self.amount_decimal_separators,
        )

    def _read_all_texts(self, image_crop: np.ndarray, variant: str = "original") -> List[OCRTextCandidate]:
        def read_candidate(engine: BaseOCREngine) -> OCRTextCandidate:
            try:
                return OCRTextCandidate(
                    engine=engine.name,
                    text=engine.read_text(image_crop).strip(),
                    variant=variant,
                )
            except Exception as exc:
                logger.error("OCR text read failed for '%s': %s", engine.name, exc)
                return OCRTextCandidate(engine=engine.name, text="", variant=variant)

        if not self.parallel or len(self.engines) <= 1:
            return [read_candidate(engine) for engine in self.engines]

        candidates_by_engine: Dict[str, OCRTextCandidate] = {}
        with ThreadPoolExecutor(max_workers=len(self.engines), thread_name_prefix="poker-ocr") as executor:
            futures = {executor.submit(read_candidate, engine): engine.name for engine in self.engines}
            for future in as_completed(futures):
                candidate = future.result()
                candidates_by_engine[candidate.engine] = candidate

        return [
            candidates_by_engine.get(engine.name, OCRTextCandidate(engine=engine.name, text="", variant=variant))
            for engine in self.engines
        ]

    def _read_all_amounts(self, image_crop: np.ndarray) -> List[OCRAmountCandidate]:
        candidates: List[OCRAmountCandidate] = []
        for text_candidate in self._read_all_texts(image_crop):
            candidates.append(
                OCRAmountCandidate(
                    engine=text_candidate.engine,
                    raw_text=text_candidate.text,
                    value=self._parse_amount_with_current_format(text_candidate.text),
                )
            )
        return candidates

    def _read_amounts_until_valid(self, image_crop: np.ndarray) -> Tuple[List[OCRAmountCandidate], Optional[OCRAmountCandidate]]:
        candidates: List[OCRAmountCandidate] = []
        for engine in self.engines:
            try:
                raw_text = engine.read_text(image_crop).strip()
            except Exception as exc:
                logger.error("OCR text read failed for '%s': %s", engine.name, exc)
                raw_text = ""

            candidate = OCRAmountCandidate(
                engine=engine.name,
                raw_text=raw_text,
                value=self._parse_amount_with_current_format(raw_text),
            )
            candidates.append(candidate)
            if candidate.value is not None:
                return candidates, candidate

        return candidates, None

    @staticmethod
    def _text_confidence(text: str) -> float:
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return 0.0

        alpha_numeric_ratio = sum(char.isalnum() for char in normalized) / max(len(normalized), 1)
        length_factor = min(len(normalized) / 8.0, 1.0)
        return round((alpha_numeric_ratio * 0.45) + (length_factor * 0.55), 3)

    @classmethod
    def _amount_confidence(cls, raw_text: str, value: Optional[float], agreement_bonus: float = 0.0) -> float:
        if value is None:
            return 0.0
        digits_factor = min(sum(char.isdigit() for char in raw_text) / 6.0, 1.0)
        return round(min(1.0, 0.55 + (digits_factor * 0.3) + agreement_bonus), 3)

    def _finalize_text_metadata(
        self,
        selected_engine: str,
        selected_text: str,
        candidates: List[OCRTextCandidate],
        *,
        field: str = "text",
        selected_variant: str = "",
        candidate_score_overrides: Optional[Dict[Tuple[str, str], float]] = None,
        selected_confidence: Optional[float] = None,
    ) -> None:
        non_empty = [candidate.text for candidate in candidates if candidate.text]
        agreement = "full" if len(set(non_empty)) == 1 and non_empty else "partial" if len(non_empty) > 1 else "none"
        candidate_rows = []
        engine_scores: Dict[str, float] = {}
        resolved_selected_confidence = selected_confidence
        for candidate in candidates:
            score = (
                candidate_score_overrides.get((candidate.engine, candidate.variant), self._text_confidence(candidate.text))
                if candidate_score_overrides
                else self._text_confidence(candidate.text)
            )
            engine_scores[candidate.engine] = max(engine_scores.get(candidate.engine, 0.0), score)
            candidate_rows.append(
                {
                    "engine": candidate.engine,
                    "variant": candidate.variant,
                    "text": candidate.text,
                    "score": score,
                }
            )
            if (
                resolved_selected_confidence is None
                and candidate.engine == selected_engine
                and candidate.variant == selected_variant
            ):
                resolved_selected_confidence = score
        self.last_metadata = {
            **self.last_metadata,
            "field": field,
            "selected_engine": selected_engine,
            "selected_text": selected_text,
            "selected_variant": selected_variant,
            "selected_amount": None,
            "selected_confidence": resolved_selected_confidence or 0.0,
            "engine_scores": engine_scores,
            "agreement": agreement,
            "candidates": candidate_rows,
        }

    def _finalize_amount_metadata(
        self,
        selected_engine: str,
        selected_amount: Optional[float],
        candidates: List[OCRAmountCandidate],
        agreement: str,
    ) -> None:
        agreement_bonus = 0.15 if agreement == "consensus" else 0.0
        candidate_rows = []
        engine_scores: Dict[str, float] = {}
        for candidate in candidates:
            score = self._amount_confidence(candidate.raw_text, candidate.value, agreement_bonus if candidate.value == selected_amount and agreement == "consensus" else 0.0)
            engine_scores[candidate.engine] = score
            candidate_rows.append({"engine": candidate.engine, "text": candidate.raw_text, "value": candidate.value, "score": score})
        self.last_metadata = {
            **self.last_metadata,
            "field": "amount",
            "selected_engine": selected_engine,
            "selected_text": next((candidate.raw_text for candidate in candidates if candidate.engine == selected_engine), ""),
            "selected_amount": selected_amount,
            "selected_confidence": engine_scores.get(selected_engine, 0.0),
            "engine_scores": engine_scores,
            "agreement": agreement,
            "candidates": candidate_rows,
        }

    def read_text(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0 or not self.engines:
            self._finalize_text_metadata("", "", [])
            return ""

        candidates = self._read_all_texts(image_crop)
        if self.mode == "priority":
            selected = candidates[0] if candidates else OCRTextCandidate(engine="", text="")
        else:
            selected = next((candidate for candidate in candidates if candidate.text), candidates[0] if candidates else OCRTextCandidate(engine="", text=""))

        self._finalize_text_metadata(selected.engine, selected.text, candidates)
        return selected.text

    @staticmethod
    def _build_player_name_variants(image_crop: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        variants: List[Tuple[str, np.ndarray]] = [("original", image_crop)]
        if image_crop is None or image_crop.size == 0:
            return variants

        gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
        normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        upscaled = cv2.resize(normalized, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        upscaled_bgr = cv2.cvtColor(upscaled, cv2.COLOR_GRAY2BGR)
        variants.append(("upscaled_contrast", upscaled_bgr))

        _, threshold = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        threshold_bgr = cv2.cvtColor(threshold, cv2.COLOR_GRAY2BGR)
        variants.append(("threshold", threshold_bgr))
        return variants

    @classmethod
    def _player_name_candidate_score(cls, text: str, variant: str, support_count: int = 1) -> float:
        candidate = sanitize_player_name(text)
        if not candidate:
            return 0.0

        base_score = cls._text_confidence(candidate)
        if is_placeholder_player_name(candidate):
            return round(min(base_score * 0.1, 0.08), 3)
        if is_probable_ui_name(candidate):
            return round(min(base_score * 0.15, 0.12), 3)

        condensed = candidate.replace(" ", "")
        alpha_count = sum(char.isalpha() for char in candidate)
        digit_count = sum(char.isdigit() for char in candidate)

        score = base_score
        if 4 <= len(condensed) <= 14:
            score += 0.12
        elif 3 <= len(condensed) <= 18:
            score += 0.08

        if alpha_count and digit_count:
            score += 0.08
        elif alpha_count >= 4:
            score += 0.05

        if any(char in "._-" for char in candidate):
            score += 0.04

        tokens = [token for token in candidate.split(" ") if token]
        if len(tokens) == 1:
            score += 0.05
        elif len(tokens) == 2 and min(len(token) for token in tokens) >= 3:
            score += 0.03

        if variant == "original":
            score += 0.04
        elif variant == "upscaled_contrast":
            score += 0.02

        if support_count > 1:
            score += min(0.2, 0.1 * (support_count - 1))

        return round(min(score, 1.0), 3)

    def read_player_name(self, image_crop: np.ndarray) -> str:
        if image_crop is None or image_crop.size == 0 or not self.engines:
            self._finalize_text_metadata("", "", [], field="player_name")
            return ""

        variants = self._build_player_name_variants(image_crop)
        candidates = self._read_all_texts(variants[0][1], variant=variants[0][0])

        def choose_best_player_name(
            items: List[OCRTextCandidate],
        ) -> Tuple[Optional[OCRTextCandidate], str, float, Dict[Tuple[str, str], float]]:
            support_counts: Counter[str] = Counter()
            sanitized_by_key: Dict[Tuple[str, str], str] = {}
            for item in items:
                sanitized = sanitize_player_name(item.text)
                sanitized_by_key[(item.engine, item.variant)] = sanitized
                if is_usable_player_name(sanitized):
                    support_counts[sanitized] += 1

            best_candidate: Optional[OCRTextCandidate] = None
            best_text = ""
            best_score = 0.0
            score_overrides: Dict[Tuple[str, str], float] = {}
            for item in items:
                candidate_key = (item.engine, item.variant)
                sanitized = sanitized_by_key.get(candidate_key, "")
                support_count = support_counts.get(sanitized, 0)
                score = self._player_name_candidate_score(sanitized, item.variant, support_count=support_count)
                score_overrides[candidate_key] = score
                if not is_usable_player_name(sanitized):
                    continue
                if (
                    score > best_score
                    or (
                        score == best_score
                        and best_candidate is not None
                        and support_count > support_counts.get(best_text, 0)
                    )
                    or best_candidate is None
                ):
                    best_candidate = item
                    best_text = sanitized
                    best_score = score

            return best_candidate, best_text, best_score, score_overrides

        selected_candidate, selected_text, selected_score, score_overrides = choose_best_player_name(candidates)
        has_consensus = bool(
            selected_text
            and sum(
                1
                for item in candidates
                if sanitize_player_name(item.text) == selected_text and is_usable_player_name(item.text)
            )
            >= 2
        )

        if (not selected_text or selected_score < 0.82) and not has_consensus:
            for variant_name, variant_image in variants[1:]:
                candidates.extend(self._read_all_texts(variant_image, variant=variant_name))
            selected_candidate, selected_text, selected_score, score_overrides = choose_best_player_name(candidates)

        if selected_candidate is None or not selected_text:
            self._finalize_text_metadata(
                "",
                "",
                candidates,
                field="player_name",
                candidate_score_overrides=score_overrides,
                selected_confidence=0.0,
            )
            return ""

        self._finalize_text_metadata(
            selected_candidate.engine,
            selected_text,
            candidates,
            field="player_name",
            selected_variant=selected_candidate.variant,
            candidate_score_overrides=score_overrides,
            selected_confidence=selected_score,
        )
        return selected_text

    @staticmethod
    def _preprocess_for_amount(image_crop: np.ndarray) -> np.ndarray:
        if image_crop is None or image_crop.size == 0:
            return image_crop
        try:
            # 1. Upscale for better font recognition
            enlarged = cv2.resize(image_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            
            # 2. Convert to HSV
            hsv = cv2.cvtColor(enlarged, cv2.COLOR_BGR2HSV)
            
            # 3. Create Yellow Mask (Poker UI amounts are often yellow or white)
            lower_yellow = np.array([20, 50, 150])
            upper_yellow = np.array([40, 255, 255])
            mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
            
            # 4. Create White Mask
            lower_white = np.array([0, 0, 180])
            upper_white = np.array([179, 40, 255])
            mask_white = cv2.inRange(hsv, lower_white, upper_white)
            
            # 5. Combine Masks
            combo_mask = cv2.bitwise_or(mask_white, mask_yellow)
            
            # 6. Create Binary Image (Black text on White background)
            binary = np.full(enlarged.shape[:2], 255, dtype=np.uint8)
            binary[combo_mask > 0] = 0
            
            # Return BGR so engines relying on 3 channels don't break
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        except Exception as exc:
            logger.warning(f"Amount preprocessing failed: {exc}")
            return image_crop

    def read_and_parse_amount(self, image_crop: np.ndarray) -> Optional[float]:
        if image_crop is None or image_crop.size == 0 or not self.engines:
            self._finalize_amount_metadata("", None, [], "none")
            return None

        # Pre-traitement agressif de l'image specialement configure pour les montants
        image_crop = self._preprocess_for_amount(image_crop)

        if self.mode == "consensus_amounts":
            candidates = self._read_all_amounts(image_crop)
            valid_candidates = [candidate for candidate in candidates if candidate.value is not None]

            if not valid_candidates:
                self._finalize_amount_metadata("", None, candidates, "none")
                return None

            counts = Counter(round(candidate.value or 0.0, 2) for candidate in valid_candidates)
            consensus_value, consensus_count = counts.most_common(1)[0]
            if consensus_count >= 2:
                selected = next(candidate for candidate in valid_candidates if round(candidate.value or 0.0, 2) == consensus_value)
                self._finalize_amount_metadata(selected.engine, selected.value, candidates, "consensus")
                return selected.value

            selected = valid_candidates[0]
            self._finalize_amount_metadata(selected.engine, selected.value, candidates, "fallback")
            return selected.value

        candidates, selected = self._read_amounts_until_valid(image_crop)
        if selected is None:
            self._finalize_amount_metadata("", None, candidates, "none")
            return None

        agreement = "priority" if self.mode == "priority" else "fallback"
        self._finalize_amount_metadata(selected.engine, selected.value, candidates, agreement)
        return selected.value


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ocr = PokerOCR()

