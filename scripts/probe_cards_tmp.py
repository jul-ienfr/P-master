# -*- coding: utf-8 -*-
"""Diagnostic numerique du miss hero-cards sur l'image temoin.
1) Fichier modele YOLO + chargement ultralytics.
2) Replay PokerDetector.analyze_frame complet + dump candidats cartes YOLO bruts.
3) Balayage pleine-frame: fenetres 90x70 les plus claires (hors bande basse y>1030).
"""
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIT = ROOT / "dataset/needs_annotation/failed_20260903_111458_115.jpg"
img = cv2.imread(str(WIT))
H, W = img.shape[:2]
print(f"witness h={H} w={W}", flush=True)

print("--- modeles ---", flush=True)
for p in sorted((ROOT / "models").glob("*")):
    print(f"models/{p.name} {p.stat().st_size} bytes", flush=True)

print("--- chargement YOLO ---", flush=True)
try:
    from src.vision.detector import PokerDetector

    det = PokerDetector()
    print(f"detector.model={'OK' if det.model is not None else 'NONE'}", flush=True)
    print(f"pipeline={det.pipeline}", flush=True)
    print(f"fallback available={det.fallback_detector.available()}", flush=True)
    if det.model is not None:
        yolo_state = det._run_yolo_detection(img, 0.6)
        print(
            f"yolo: hero={len(yolo_state.hero_cards)} board={len(yolo_state.board_cards)} "
            f"buttons={len(yolo_state.action_buttons)} pots={len(yolo_state.pots)} "
            f"split={yolo_state.metadata.get('card_split_source')}",
            flush=True,
        )
        for d in yolo_state.hero_cards + yolo_state.board_cards:
            print(
                f"  card cls={d.class_name} conf={d.confidence:.3f} bbox={d.bbox}",
                flush=True,
            )
        for b in yolo_state.action_buttons:
            print(
                f"  btn cls={b.class_name} conf={b.confidence:.3f} bbox={b.bbox}",
                flush=True,
            )
    print("--- analyze_frame complet ---", flush=True)
    state = det.analyze_frame(img)
    print(
        f"mode={state.metadata.get('detector_mode')} table={state.metadata.get('table_detected')} "
        f"fallback={state.metadata.get('fallback_reason')} preset={state.metadata.get('fallback_preset')}",
        flush=True,
    )
    for sec in ("hero_cards", "board_cards", "action_buttons"):
        for d in getattr(state, sec):
            print(
                f"  {sec} cls={d.class_name} conf={d.confidence:.3f} bbox={d.bbox}",
                flush=True,
            )
except Exception:
    traceback.print_exc()

print("--- balayage fenetres 90x70 (top clarte, y2<=1030) ---", flush=True)
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
wins = []
for y in range(0, min(H, 1030) - 70, 15):
    for x in range(0, W - 90, 15):
        w = g[y : y + 70, x : x + 90]
        wins.append((float((w > 140).mean()), float(w.mean()), x, y))
wins.sort(key=lambda t: -t[0])
for frac, mean, x, y in wins[:12]:
    print(
        f"win x={x} y={y} x2={x+90} y2={y+70} frac140={frac:.3f} mean={mean:.0f}",
        flush=True,
    )
print("done", flush=True)
