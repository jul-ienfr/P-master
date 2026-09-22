# -*- coding: utf-8 -*-
"""Zoom fin hero : crop x700-1300/y800-1050 + stats par sous-fenetre 60x84."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIT = ROOT / "dataset/needs_annotation/failed_20260903_111458_115.jpg"
img = cv2.imread(str(WIT))

# crop serre autour des dos + cartes claires de droite
x0, y0, x1, y1 = 700, 800, 1320, 1050
crop = img[y0:y1, x0:x1]
out = ROOT / "temp_probe" / "z_hero_tight.png"
cv2.imwrite(str(out), cv2.resize(crop, None, fx=1, fy=1))
print(f"wrote {out} shape={crop.shape}", flush=True)

g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
# grille de stats : decoupage en cellules 62x50 (10 col x 5 lig) pour localiser le sombre
ch, cw = crop.shape[:2]
for row in range(5):
    line = []
    for col in range(10):
        cx0, cy0 = col * cw // 10, row * ch // 5
        cx1, cy1 = (col + 1) * cw // 10, (row + 1) * ch // 5
        cell = g[cy0:cy1, cx0:cx1]
        line.append(f"{cell.mean():3.0f}/{float((cell > 140).mean()):.2f}")
    print(f"row{row} y={y0 + row * ch // 5}: " + " ".join(line), flush=True)

# bordures verticales sombres->clair pour trouver les rectangles (seuil sur gradient x)
gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
col_energy = np.abs(gx).mean(axis=0)
peaks = np.where(col_energy > col_energy.mean() + 2 * col_energy.std())[0]
groups = []
for p in peaks:
    if groups and p - groups[-1][-1] <= 4:
        groups[-1].append(int(p))
    else:
        groups.append([int(p)])
print("bords verticaux (x crop):", [(gr[0], gr[-1]) for gr in groups], flush=True)
print("bords verticaux (x absolu):", [(x0 + gr[0], x0 + gr[-1]) for gr in groups], flush=True)
print("done", flush=True)
