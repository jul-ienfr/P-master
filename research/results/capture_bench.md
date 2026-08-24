# Bench capture écran — WGC vs dxcam

`python scripts/bench_capture.py [hwnd] [--frames N]`

Mesuré le 2026-08-24 sur la machine de prod (GTX 1060 3Go, Win11, fenêtre
VS Code 1920×1032, 150 frames/backend) :

| Backend | Débit | Grab médiane | Post-traitement |
|---|---|---|---|
| **WGC** (HWND, DWM) | 45.0 fps | ~0 ms (cache asynchrone) | 0.40 ms/frame |
| **dxcam** (écran) | 75.6 fps | 2.17 ms | ~0 ms |

## Lecture

- Les deux débits dépassent largement le besoin runtime (~10–30 fps).
- Le débit WGC est borné par la fréquence de rendu de la fenêtre cible et
  la boucle de polling consommateur (`sleep 2 ms`) ; la lecture elle-même
  est gratuite (dernière frame cachée par le thread natif).
- dxcam est légèrement plus rapide en latence pure mais lit les pixels
  écran : fenêtre occlusée/minimisée ⇒ contenu faux ou vide.
- Coût consommateur WGC (0.40 ms/frame pour une conversion grayscale
  pleine fenêtre) est négligeable face au budget décision 1000 ms.

## Décision retenue (Phase 2.2)

WGC prioritaire dès qu'un HWND est connu (exactitude > micro-latence),
fallback dxcam → BitBlt → ImageGrab sinon. La sonde de démarrage de 1 s
garantit un repli silencieux si la session ne produit pas.
