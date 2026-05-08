@echo off
title Apprentissage du YOLO Global
color 0B

echo.
echo ============================================================
echo   🧠 PHASE 1 : ETIQUETAGE AUTOMATIQUE DES CARTES (AUTO-LABEL)
echo ============================================================
echo.
python src\scripts\auto_annotate_templates.py --dataset PokerStars_NLHE_6Max

echo.
echo ============================================================
echo   🧹 PHASE 2 : NETTOYAGE DU CACHE YOLO
echo ============================================================
echo.
if exist "dataset\PokerStars_NLHE_6Max\*.cache" (
    del /Q "dataset\PokerStars_NLHE_6Max\*.cache"
)

echo.
echo ============================================================
echo   🚀 PHASE 3 : ENTRAINEMENT DU RESEAU NEURONAL (YOLO)
echo ============================================================
echo.
python src\scripts\train_yolo.py --data dataset\PokerStars_NLHE_6Max\dataset.yaml

echo.
echo ✅ Entrainement termine avec succes !
pause
