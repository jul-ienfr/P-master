# -*- coding: utf-8 -*-
"""Localise tous les rectangles de cartes + coin ancre sur le temoin (coords absolues)."""
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
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

print("=== composantes blanches>140 aire>=1500 (cartes entieres) ===", flush=True)
mask = ((g > 140).astype(np.uint8)) * 255
n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
rects = []
for i in range(1, n):
    x, y, w, h, area = [int(v) for v in stats[i]]
    if area < 1500:
        continue
    rects.append((area, x, y, w, h))
rects.sort(key=lambda r: -r[0])
for area, x, y, w, h in rects[:20]:
    crop = g[y : y + h, x : x + w]
    print(
        f"area={area} box=({x},{y},{x+w},{y+h}) w={w} h={h} "
        f"mean={crop.mean():.0f} bright160={float((crop > 160).mean()):.2f}",
        flush=True,
    )

print("=== coin cadre haut-gauche : patch candidat ancre ===", flush=True)
# le coin arrondi blanc du cadre : chercher le pixel le plus clair pres de (292,87)
corner = g[60:140, 260:340]
mn, mx, _, mxloc = cv2.minMaxLoc(corner)
print(f"patch mean={corner.mean():.1f} max={mx} maxloc_abs=({260+mxloc[0]},{60+mxloc[1]})", flush=True)
anchor_crop = img[80:125, 285:320]
p = ROOT / "temp_probe" / "anchor_candidate.png"
cv2.imwrite(str(p), anchor_crop)
print(f"wrote {p} shape={anchor_crop.shape}", flush=True)

print("=== boutons bas-droite : composantes claires y>850 x>1050 ===", flush=True)
sub = g[850:, 1050:]
sm = ((sub > 100).astype(np.uint8)) * 255
n2, _, st2, _ = cv2.connectedComponentsWithStats(sm, 8)
btns = []
for i in range(1, n2):
    x, y, w, h, area = [int(v) for v in st2[i]]
    if area < 3000 or w < 60 or h < 25:
        continue
    btns.append((area, 1050 + x, 850 + y, w, h))
btns.sort(key=lambda r: -r[0])
for area, x, y, w, h in btns[:10]:
    print(f"area={area} box=({x},{y},{x+w},{y+h})", flush=True)
print("done", flush=True)
