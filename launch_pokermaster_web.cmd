@echo off
setlocal
set "ROOT=%~dp0website"
if not exist "%ROOT%\package.json" (
  echo PokerMaster web workspace not found at "%ROOT%"
  exit /b 1
)

echo Launching PokerMaster V2 web-only mode...
echo Workspace: %ROOT%
echo This starts Vite without rebuilding the Rust shell.
echo Open http://localhost:5173 in your browser.

pushd "%ROOT%"
call npm run dev -- --host 127.0.0.1
set EXIT_CODE=%ERRORLEVEL%
popd

exit /b %EXIT_CODE%
