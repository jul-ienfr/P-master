import numpy as np

from src.runtime.player_identity_state import PlayerIdentityState
from src.vision.player_name_reader import PlayerNameReader


def test_player_name_reader_resolves_and_exposes_evidence_metadata():
    class FakeOCR:
        def read_player_name(self, image_crop):
            del image_crop
            return "Brucy20"

        def get_metadata(self):
            return {
                "selected_engine": "rapidocr",
                "selected_text": "Brucy20",
                "selected_confidence": 0.91,
            }

    reader = PlayerNameReader(FakeOCR())
    cache = {}
    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    result = reader.read_name("seat_2", crop, cache)

    assert result.selected_name == "Brucy20"
    assert result.resolution_source == "live_ocr"
    assert result.evidence.selected_value == "Brucy20"
    assert cache["seat_2"] == "Brucy20"


def test_player_identity_state_promotes_repeated_name_to_confirmed():
    identity_state = PlayerIdentityState()

    first = identity_state.update("seat_1", "Villain42", "live_ocr")
    second = identity_state.update("seat_1", "Villain42", "live_ocr")

    assert first["state"] == "tentative"
    assert second["state"] == "confirmed"
