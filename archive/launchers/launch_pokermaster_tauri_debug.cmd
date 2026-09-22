@echo off
setlocal
echo Launching PokerMaster V2 Tauri debug build...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_pokermaster_v2.ps1" -BuildDebug
set EXIT_CODE=%ERRORLEVEL%
exit /b %EXIT_CODE%
