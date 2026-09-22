# -*- coding: utf-8 -*-
"""Zoom diagnostique hero-cards temoin : crops absolus + stats + sweep carte."""
import sys
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

OUT = ROOT / "temp_probe"
OUT.mkdir(exist_ok=True)

zones = {
    # candidat hero bas-centre large
    "z_hero": (0.30, 0.72, 0.75, 1.0),
    # board centre
    "z_board": (0.25, 0.35, 0.75, 0.65),
    # villain haut-droite (TR 4 cartes)
    "z_villain": (0.55, 0.0, 1.0, 0.35),
    # boutons bas-droite
    "z_buttons": (0.55, 0.80, 1.0, 1.0),
}
for name, (x0r, y0r, x1r, y1r) in zones.items():
    x0, y0, x1, y1 = int(x0r * W), int(y0r * H), int(x1r * W), int(y1r * H)
    crop = img[y0:y1, x0:x1]
    p = OUT / f"{name}.png"
    ok = cv2.imwrite(str(p), crop)
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    print(
        f"{name}: box=({x0},{y0},{x1},{y1}) wrote={ok} size={p.stat().st_size if ok else 0} "
        f"mean={g.mean():.1f} std={g.std():.1f} max={int(g.max())} "
        f"frac140={float((g > 140).mean()):.4f}",
        flush=True,
    )

# sweep fin : fenetres 60x84 (ratio carte ~0.71) sur bande hero y 780..1000
print("--- sweep hero-band 60x84 ---", flush=True)
gfull = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
wins = []
for y in range(750, 1000 - 84, 10):
    for x in range(350, 1000 - 60, 10):
        w = gfull[y : y + 84, x : x + 60]
        wins.append((float((w > 140).mean()), float(w.mean()), float(w.std()), x, y))
wins.sort(key=lambda t: -t[0])
for frac, mean, std, x, y in wins[:10]:
    print(f"win x={x} y={y} x2={x+60} y2={y+84} frac140={frac:.3f} mean={mean:.0f} std={std:.0f}", flush=True)
print("done", flush=True)
