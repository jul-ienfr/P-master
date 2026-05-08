@echo off
setlocal
title PokerMaster - Activer Shadow Mode
set "ROOT=%~dp0.."
cd /d "%ROOT%"

echo.
echo [PokerMaster] Activation du shadow mode...
echo [PokerMaster] Attente de l'API locale sur http://127.0.0.1:8005 ...
echo.
powershell -NoLogo -ExecutionPolicy Bypass -File "%ROOT%\scripts\enable_shadow_mode.ps1"
if errorlevel 1 (
  echo.
  echo [ERREUR] Impossible d'activer le shadow mode.
  echo Verifie que le bot tourne bien et que l'API repond sur http://127.0.0.1:8005
  echo.
  pause
  exit /b 1
)

echo.
echo [OK] Shadow mode confirme par le runtime.
echo Tu peux maintenant laisser tourner le bot 10 a 15 minutes.
echo.
pause
