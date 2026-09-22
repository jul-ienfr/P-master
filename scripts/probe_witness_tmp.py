# -*- coding: utf-8 -*-
"""Sonde diagnostique : positions hero-cards temoin + coin haut-gauche + tailles templates."""
import cv2
import numpy as np
from pathlib import Path

WIT = Path("dataset/needs_annotation/failed_20260903_111458_115.jpg")
img = cv2.imread(str(WIT))
H, W = img.shape[:2]
print(f"witness shape: h={H} w={W}")

# 1) Blancs bas de l'image (moitie basse) -> bbox cartes hero
low = img[H // 2 :, :]
gray = cv2.cvtColor(low, cv2.COLOR_BGR2GRAY)
mask = ((gray > 140).astype(np.uint8)) * 255
n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
cands = []
for i in range(1, n):
    x, y, w, h, area = [int(v) for v in stats[i]]
    if area < 800 or w < 25 or h < 30:
        continue
    asp = w / max(h, 1)
    if asp < 0.3 or asp > 2.5:
        continue
    cands.append((area, x, y + H // 2, w, h))
cands.sort(key=lambda c: -c[0])
for area, x, y, w, h in cands[:8]:
    print(f"white-blob area={area} x={x} y={y} w={w} h={h} x2={x+w} y2={y+h}")

# 2) Coin haut-gauche : stats patch 0,0,60,60 + save crop
corner = img[0:80, 0:120]
print(f"corner crop mean={corner.mean():.1f} std={corner.std():.1f}")
cv2.imwrite("temp_tl.jpg", img[0:150, 0:220])
cv2.imwrite("temp_hero.jpg", img[H // 2 :, :])
print("saved temp_tl.jpg temp_hero.jpg")

# 3) Tailles templates 4s/4c vs blob hero estime
for name in ("4s", "4c", "topleft_corner", "covered_card"):
    p = Path(f"poker/official-party-poker/stable/assets/{name}.png")
    t = cv2.imread(str(p))
    print(f"asset {name}: shape={None if t is None else t.shape} bytes={p.stat().st_size}")

# 4) Erreur matchTemplate coin actuel sur frame (echelles 0.75..2.5)
anchor = cv2.imread("poker/official-party-poker/stable/assets/topleft_corner.png")
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
ag = cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY)
for s in (0.75, 1.0, 1.5, 2.0, 2.27, 2.5):
    tw, th = max(4, round(ag.shape[1] * s)), max(4, round(ag.shape[0] * s))
    if tw >= W or th >= H:
        print(f"scale {s}: template {tw}x{th} trop grand, skip")
        continue
    rs = cv2.resize(ag, (tw, th), interpolation=cv2.INTER_CUBIC if s >= 1 else cv2.INTER_AREA)
    r = cv2.matchTemplate(g, rs, cv2.TM_SQDIFF_NORMED)
    mn, _, mnloc, _ = cv2.minMaxLoc(r)
    print(f"anchor scale={s} tpl={tw}x{th} err={mn:.4f} loc={mnloc}")
