import numpy as np

from src.vision import ocr as ocr_module


class FakeTextEngine:
    def __init__(self, name: str, responses: dict[tuple[int, int], str]):
        self.name = name
        self._responses = responses

    def read_text(self, image_crop: np.ndarray) -> str:
        return self._responses.get((image_crop.shape[0], image_crop.shape[1]), "")


def build_test_ocr(*engines: FakeTextEngine) -> ocr_module.PokerOCR:
    ocr = ocr_module.PokerOCR.__new__(ocr_module.PokerOCR)
    ocr.mode = "consensus_amounts"
    ocr.parallel = False
    ocr.enabled_engines = [engine.name for engine in engines]
    ocr.engines = list(engines)
    ocr.last_metadata = {
        **ocr_module.PokerOCR._empty_metadata(),
        "requested_engines": [engine.name for engine in engines],
        "loaded_engines": [engine.name for engine in engines],
        "mode": ocr.mode,
        "parallel": ocr.parallel,
    }
    return ocr


def test_read_player_name_prefers_usable_candidate_over_first_non_empty_noise(monkeypatch):
    original = np.zeros((10, 10, 3), dtype=np.uint8)
    enhanced = np.zeros((20, 20, 3), dtype=np.uint8)
    threshold = np.zeros((20, 24, 3), dtype=np.uint8)

    ocr = build_test_ocr(
        FakeTextEngine("surya", {(10, 10): "Suivr", (20, 20): "Suivr", (20, 24): "Suivr"}),
        FakeTextEngine("easyocr", {(10, 10): "", (20, 20): "Nick Deb01", (20, 24): "Nick Deb01"}),
    )
    monkeypatch.setattr(
        ocr,
        "_build_player_name_variants",
        lambda image_crop: [
            ("original", original),
            ("upscaled_contrast", enhanced),
            ("threshold", threshold),
        ],
    )

    resolved = ocr.read_player_name(original)
    metadata = ocr.get_metadata()

    assert resolved == "Nick Deb01"
    assert metadata["field"] == "player_name"
    assert metadata["selected_engine"] == "easyocr"
    assert metadata["selected_variant"] == "upscaled_contrast"
    assert any(candidate["text"] == "Suivr" for candidate in metadata["candidates"])


def test_read_player_name_returns_empty_when_only_ui_or_numeric_noise_is_found(monkeypatch):
    original = np.zeros((10, 10, 3), dtype=np.uint8)
    enhanced = np.zeros((20, 20, 3), dtype=np.uint8)

    ocr = build_test_ocr(
        FakeTextEngine("surya", {(10, 10): "Passer", (20, 20): "Passer"}),
        FakeTextEngine("easyocr", {(10, 10): "150.4", (20, 20): "150.4"}),
    )
    monkeypatch.setattr(
        ocr,
        "_build_player_name_variants",
        lambda image_crop: [
            ("original", original),
            ("upscaled_contrast", enhanced),
        ],
    )

    resolved = ocr.read_player_name(original)
    metadata = ocr.get_metadata()

    assert resolved == ""
    assert metadata["field"] == "player_name"
    assert metadata["selected_engine"] == ""
    assert metadata["selected_text"] == ""
