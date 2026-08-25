"""Tests de la sonde pixel rapide (src/bot/pixel_probe.py)."""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.pixel_probe import FastPixelProbe


def test_is_our_turn_rejects_none_and_non_color_frames():
    assert FastPixelProbe.is_our_turn(None) is False
    gray = np.zeros((100, 100), dtype=np.uint8)
    assert FastPixelProbe.is_our_turn(gray) is False


def test_is_our_turn_detects_red_button_pixels():
    frame = np.zeros((300, 600, 3), dtype=np.uint8)
    # zone des boutons = coin bas-droit : dessiner un bloc rouge vif (BGR)
    frame[260:290, 450:580] = (0, 0, 255)
    assert FastPixelProbe.is_our_turn(frame) is True


def test_is_our_turn_false_without_red():
    frame = np.full((300, 600, 3), 40, dtype=np.uint8)
    assert FastPixelProbe.is_our_turn(frame) is False


def test_is_our_turn_handles_tiny_frames():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    # roi vide possible -> pas d'exception, résultat booléen
    assert isinstance(FastPixelProbe.is_our_turn(frame), bool)
