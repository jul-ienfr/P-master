@echo off
title PokerMaster Routine d'Entrainement YOLO
color 0E

echo.
echo ============================================================
echo   🚀 PROGRAMME D'ENTRAINEMENT DU YOLO UNIVERSEL
echo ============================================================
echo.
echo Etape 1: Lancement du robot PokerMaster en arriere-plan...
start "PokerMaster Runtime" cmd /c "lancer.cmd"
timeout /t 3 /nobreak >nul

echo Etape 2: Lancement du module de capture (1 image toutes les 5 sec)...
start "Capture Vision YOLO" cmd /c "capture_images.cmd"

echo.
echo ✅ Succes ! Les deux processus tournent.
echo Jouez normalement sur vos tables PokerStars. Les images s'accumuleront
echo toutes seules dans 'dataset\PokerStars_NLHE_6Max\raw_images\'.
echo.
echo Une fois la session de prise de captures terminee, fermez 
echo manuellement la fenetre noire "Capture Vision YOLO".
echo.
pause
