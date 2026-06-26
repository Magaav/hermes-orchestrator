@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."

echo WASM Agent Android OAuth verification fallback
echo Preferred path: Open wasm-agent Windows app ^> Diagnostics ^> Verify Android OAuth.
rem Fallback commands: adb devices -l; horc simulate android --device --interactive-oauth
echo.

where adb >nul 2>nul
if errorlevel 1 (
  echo adb is missing.
  echo Install Android SDK Platform Tools, add platform-tools to PATH, then reopen this window.
  echo Download: https://developer.android.com/tools/releases/platform-tools
  pause
  exit /b 2
)

where horc >nul 2>nul
if errorlevel 1 (
  echo horc is missing from PATH.
  echo Run this from a WASM Agent development shell where horc is available.
  pause
  exit /b 4
)

echo checking adb
adb version
echo.

set /a "WAIT_SECONDS=180"
if not "%WASM_AGENT_ANDROID_OAUTH_DEVICE_WAIT_SECONDS%"=="" set /a "WAIT_SECONDS=%WASM_AGENT_ANDROID_OAUTH_DEVICE_WAIT_SECONDS%"
set /a "WAIT_LEFT=%WAIT_SECONDS%"

:poll_device
set "DEVICE_STATE=waiting"
for /f "skip=1 tokens=1,2,*" %%A in ('adb devices -l 2^>nul') do (
  if "%%B"=="device" set "DEVICE_STATE=device"
  if "%%B"=="unauthorized" set "DEVICE_STATE=unauthorized"
  if "%%B"=="offline" set "DEVICE_STATE=offline"
)

if "%DEVICE_STATE%"=="device" goto authorized_device
if "%DEVICE_STATE%"=="unauthorized" (
  echo unauthorized: Unlock your phone and tap Allow USB debugging.
) else if "%DEVICE_STATE%"=="offline" (
  echo phone offline: reconnect USB or toggle USB debugging.
) else (
  echo waiting for phone: plug Android phone by USB and enable USB debugging.
)

if %WAIT_LEFT% LEQ 0 (
  echo PENDING: real-device proof is still pending.
  pause
  exit /b 3
)
set /a "WAIT_LEFT-=2"
timeout /t 2 /nobreak >nul
goto poll_device

:authorized_device
echo device authorized
echo running horc simulate android --device --interactive-oauth
horc simulate android --device --interactive-oauth
set "HORC_EXIT=%ERRORLEVEL%"

set "SUMMARY=%CD%\reports\sim\android\latest\summary.md"
echo.
if exist "%SUMMARY%" (
  echo Latest report: %SUMMARY%
  echo.
  type "%SUMMARY%"
  echo.
  findstr /i /c:"- Status: PASSED" "%SUMMARY%" >nul
  if "%HORC_EXIT%"=="0" if not errorlevel 1 (
    echo PASS: Android OAuth real-device proof passed.
    pause
    exit /b 0
  )
  findstr /i /c:"- Status: PENDING" "%SUMMARY%" >nul
  if not errorlevel 1 (
    echo PENDING: real-device proof is still pending.
    pause
    exit /b 5
  )
) else (
  echo Latest report not found: %SUMMARY%
)

echo FAIL: Android OAuth real-device proof did not pass.
pause
if "%HORC_EXIT%"=="0" exit /b 5
exit /b %HORC_EXIT%
