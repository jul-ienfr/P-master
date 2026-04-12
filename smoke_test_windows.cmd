@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke_test_windows.ps1" %*
