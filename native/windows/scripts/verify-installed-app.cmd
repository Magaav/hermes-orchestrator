@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify-installed-app.ps1" -Pause
exit /b %ERRORLEVEL%
