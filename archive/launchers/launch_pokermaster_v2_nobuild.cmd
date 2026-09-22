@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_pokermaster_v2.ps1" -NoBuild %*
if errorlevel 1 (
  echo.
  echo Launch failed. Check "%~dp0launch_pokermaster_v2.log"
  pause
)
endlocal
