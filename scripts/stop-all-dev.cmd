@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-all-dev.ps1" %*
