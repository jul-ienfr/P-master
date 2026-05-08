@echo off
title Capture Dataset PokerStars
color 0b

echo.
echo ============================================================
echo   📡 Lancement de la capture d'images PokerStars (DXcam)
echo ============================================================
echo.
echo Le script va prendre 1 capture toutes les 5 secondes (100 max).
echo Les images seront sauvegardees dans : dataset\raw_images\
echo.
echo Gardez PokerStars ouvert et bien visible sur l'ecran.
echo.

python src\scripts\capture_dataset.py --interval 5.0 --max-images 100

echo.
pause
