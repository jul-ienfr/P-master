@echo off
setlocal
title PokerMaster Logs
set "ROOT=%~dp0.."
powershell -NoLogo -NoExit -Command "$host.UI.RawUI.WindowTitle = 'PokerMaster Logs'; Write-Host 'PokerMaster Logs - suivi live des fichiers runtime_manual_stdout.log et runtime_manual_stderr.log'; Write-Host '---'; Get-Content -Path '%ROOT%\log\runtime_manual_stdout.log','%ROOT%\log\runtime_manual_stderr.log' -Tail 120 -Wait"
