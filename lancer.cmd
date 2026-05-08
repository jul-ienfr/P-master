@echo off
setlocal

cd /d "%~dp0"
title PokerMaster Runtime

set "PYTHON_EXE=C:\Users\julie\AppData\Local\Programs\Python\Python312\python.exe"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%PYTHON_EXE%" (
    echo Python introuvable: "%PYTHON_EXE%"
    echo.
    pause
    exit /b 1
)

if exist "%POWERSHELL_EXE%" (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference='SilentlyContinue';" ^
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'src\\main.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" ^
        >nul 2>&1
    timeout /t 1 /nobreak >nul
)

echo Lancement du Serveur GTO (Rust)...
start "PokerMaster GTO Solver" cmd /c "cd /d "%~dp0gto_server" && cargo run --release"

echo Lancement de PokerMaster...
echo.
"%PYTHON_EXE%" main.py

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo PokerMaster s'est arrete avec le code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
