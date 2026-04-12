import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

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

SUPPORTED_OCR_ENGINES = ("doctr", "tesseract", "easyocr")
SUPPORTED_OCR_MODES = ("priority", "fallback", "consensus_amounts")


@dataclass
class OCRTextCandidate:
    engine: str
    text: str


@dataclass
class OCRAmountCandidate:
    engine: str
    raw_text: str
    value: Optional[float]


class BaseOCREngine:
    name = "base"

    def read_text(self, image_crop: np.ndarray) -> str:
        raise NotImplementedError


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
    ):
        del use_gpu
        self.mode = mode if mode in SUPPORTED_OCR_MODES else "consensus_amounts"
        self.parallel = bool(parallel)
        self.enabled_engines = self._normalize_engines(enabled_engines)
        self.engines: List[BaseOCREngine] = []
        self.last_metadata: Dict[str, object] = self._empty_metadata()
        self._load_engines()

    @classmethod
    def from_config(cls, config: Optional[dict]):
        cfg = config or {}
        return cls(
            use_gpu=bool(cfg.get("use_gpu", True)),
            enabled_engines=cfg.get("enabled_engines"),
            mode=str(cfg.get("mode", cfg.get("merge_strategy", "consensus_amounts")) or "consensus_amounts"),
            parallel=bool(cfg.get("parallel", True)),
        )

    def _normalize_engines(self, enabled_engines: Optional[Sequence[str]]) -> List[str]:
        requested = list(enabled_engines or ["doctr"])
        normalized: List[str] = []
        for engine in requested:
            key = str(engine).strip().lower()
            if key in SUPPORTED_OCR_ENGINES and key not in normalized:
                normalized.append(key)
        return normalized or ["doctr"]

    def _load_engines(self) -> None:
        engine_factories = {
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
        }

    @staticmethod
    def _empty_metadata() -> Dict[str, object]:
        return {
            "field": "",
            "mode": "consensus_amounts",
            "parallel": True,
            "supported_engines": list(SUPPORTED_OCR_ENGINES),
            "requested_engines": [],
            "loaded_engines": [],
            "unavailable_engines": {},
            "selected_engine": "",
            "selected_text": "",
            "selected_amount": None,
            "selected_confidence": 0.0,
            "engine_scores": {},
            "candidates": [],
            "agreement": "none",
        }

    def get_metadata(self) -> Dict[str, object]:
        return dict(self.last_metadata)

    @staticmethod
    def parse_amount(raw_text: str) -> Optional[float]:
        if not raw_text:
            return None

        cleaned = raw_text.upper().strip()
        cleaned = cleaned.replace("$", "").replace("€", "").replace("BB", "")
        corrections = {
            "O": "0",
            "S": "5",
            "I": "1",
            "L": "1",
            "B": "8",
            ",": ".",
            " ": "",
        }
        for wrong, right in corrections.items():
            cleaned = cleaned.replace(wrong, right)

        match = re.search(r"\d+(\.\d+)?", cleaned)
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _read_all_texts(self, image_crop: np.ndarray) -> List[OCRTextCandidate]:
        def read_candidate(engine: BaseOCREngine) -> OCRTextCandidate:
            try:
                return OCRTextCandidate(engine=engine.name, text=engine.read_text(image_crop).strip())
            except Exception as exc:
                logger.error("OCR text read failed for '%s': %s", engine.name, exc)
                return OCRTextCandidate(engine=engine.name, text="")

        if not self.parallel or len(self.engines) <= 1:
            return [read_candidate(engine) for engine in self.engines]

        candidates_by_engine: Dict[str, OCRTextCandidate] = {}
        with ThreadPoolExecutor(max_workers=len(self.engines), thread_name_prefix="poker-ocr") as executor:
            futures = {executor.submit(read_candidate, engine): engine.name for engine in self.engines}
            for future in as_completed(futures):
                candidate = future.result()
                candidates_by_engine[candidate.engine] = candidate

        return [
            candidates_by_engine.get(engine.name, OCRTextCandidate(engine=engine.name, text=""))
            for engine in self.engines
        ]

    def _read_all_amounts(self, image_crop: np.ndarray) -> List[OCRAmountCandidate]:
        candidates: List[OCRAmountCandidate] = []
        for text_candidate in self._read_all_texts(image_crop):
            candidates.append(
                OCRAmountCandidate(
                    engine=text_candidate.engine,
                    raw_text=text_candidate.text,
                    value=self.parse_amount(text_candidate.text),
                )
            )
        return candidates

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
    ) -> None:
        non_empty = [candidate.text for candidate in candidates if candidate.text]
        agreement = "full" if len(set(non_empty)) == 1 and non_empty else "partial" if len(non_empty) > 1 else "none"
        candidate_rows = []
        engine_scores: Dict[str, float] = {}
        for candidate in candidates:
            score = self._text_confidence(candidate.text)
            engine_scores[candidate.engine] = score
            candidate_rows.append({"engine": candidate.engine, "text": candidate.text, "score": score})
        self.last_metadata = {
            **self.last_metadata,
            "field": "text",
            "selected_engine": selected_engine,
            "selected_text": selected_text,
            "selected_amount": None,
            "selected_confidence": engine_scores.get(selected_engine, 0.0),
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

    def read_and_parse_amount(self, image_crop: np.ndarray) -> Optional[float]:
        if image_crop is None or image_crop.size == 0 or not self.engines:
            self._finalize_amount_metadata("", None, [], "none")
            return None

        candidates = self._read_all_amounts(image_crop)
        valid_candidates = [candidate for candidate in candidates if candidate.value is not None]

        if not valid_candidates:
            self._finalize_amount_metadata("", None, candidates, "none")
            return None

        if self.mode == "consensus_amounts":
            counts = Counter(round(candidate.value or 0.0, 2) for candidate in valid_candidates)
            consensus_value, consensus_count = counts.most_common(1)[0]
            if consensus_count >= 2:
                selected = next(candidate for candidate in valid_candidates if round(candidate.value or 0.0, 2) == consensus_value)
                self._finalize_amount_metadata(selected.engine, selected.value, candidates, "consensus")
                return selected.value

        selected = valid_candidates[0]
        agreement = "priority" if self.mode == "priority" else "fallback"
        self._finalize_amount_metadata(selected.engine, selected.value, candidates, agreement)
        return selected.value


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ocr = PokerOCR()
