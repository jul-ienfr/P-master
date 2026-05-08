@echo off
setlocal
title PokerMaster - Rapport Shadow Mode
set "ROOT=%~dp0.."
cd /d "%ROOT%"

echo.
echo [PokerMaster] Generation du rapport shadow mode...
echo.
powershell -NoLogo -ExecutionPolicy Bypass -File "%ROOT%\scripts\collect_shadow_mode_report.ps1"
if errorlevel 1 (
  echo.
  echo [ERREUR] Impossible de generer le rapport shadow mode.
  echo Verifie que le bot tourne bien et que l'API repond sur http://127.0.0.1:8005
  echo.
  pause
  exit /b 1
)

echo.
echo [OK] Rapport cree dans : log\shadow_mode_report.md
echo.
echo Le fichier va maintenant s'ouvrir si possible.
echo.
start "" "%ROOT%\log\shadow_mode_report.md"
pause
