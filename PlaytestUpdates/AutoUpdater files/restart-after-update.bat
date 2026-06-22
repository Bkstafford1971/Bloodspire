@echo off
REM Restart helper for Bloodspire auto-updater
REM This script runs the installer and restarts the app

setlocal enabledelayedexpansion

REM Get arguments: installer path and app path
set INSTALLER_PATH=%1
set APP_PATH=%2

if not defined INSTALLER_PATH (
  echo ERROR: No installer path provided
  exit /b 1
)

if not defined APP_PATH (
  echo ERROR: No app path provided
  exit /b 1
)

REM Wait a bit for app to fully close
timeout /t 2 /nobreak >nul

REM Run the installer silently and wait for it to complete
echo Running installer: !INSTALLER_PATH!
"!INSTALLER_PATH!" /S
if errorlevel 1 (
  echo ERROR: Installer failed with code %ERRORLEVEL%
  exit /b 1
)

REM Installer complete, wait a moment for files to settle
timeout /t 2 /nobreak >nul

REM Check if app path exists
if not exist "!APP_PATH!" (
  echo WARNING: App executable not found at: !APP_PATH!
  REM Try alternate location (Squirrel installs to app-VERSION folder)
  for /d %%D in (!APP_PATH!\..\..\app-*) do (
    if exist "%%D\BloodspireArena.exe" (
      set APP_PATH=%%D\BloodspireArena.exe
      goto foundapp
    )
  )
  echo ERROR: Could not find app to restart
  exit /b 1
)

:foundapp
REM Launch the updated app in background
echo Launching app: !APP_PATH!
start "" "!APP_PATH!"

REM Script done, exit
exit /b 0
