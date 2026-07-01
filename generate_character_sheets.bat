@echo off
REM Character Sheet Generator Batch File
REM Simpler version - user types the path directly

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo CHARACTER SHEET GENERATOR
echo ============================================================
echo.
echo This tool generates HTML character sheets for your warriors.
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in your PATH
    echo.
    echo Please install Python 3.x from python.org
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

echo.
echo STEP 1: Enter your Bloodspire saves directory
echo.
echo Example: C:\BloodspireChosenOne
echo Example: D:\MyGames\Bloodspire\saves
echo.
set /p SAVES_DIR="Enter your saves directory path: "

if not defined SAVES_DIR (
    echo Error: No path entered.
    pause
    exit /b 1
)

REM Expand the path in case user used quotes or tilde
for /f "delims=" %%A in ('echo %SAVES_DIR%') do set SAVES_DIR=%%~A

REM Check if directory exists
if not exist "!SAVES_DIR!" (
    echo.
    echo Error: Directory not found: !SAVES_DIR!
    echo Please make sure you entered the correct path.
    echo.
    pause
    exit /b 1
)

REM Check if teams subdirectory exists
if not exist "!SAVES_DIR!\teams" (
    echo.
    echo Error: Teams directory not found at: !SAVES_DIR!\teams
    echo.
    echo This directory needs to contain your team_*.json files.
    echo Make sure you selected your Bloodspire saves folder, not a subfolder.
    echo.
    pause
    exit /b 1
)

REM Count team files
set TEAM_COUNT=0
for /f %%F in ('dir /b "!SAVES_DIR!\teams\team_*.json" 2^>nul ^| find /c /v ""') do set TEAM_COUNT=%%F

if %TEAM_COUNT% equ 0 (
    echo.
    echo Warning: No team files found in !SAVES_DIR!\teams
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Configuration:
echo ============================================================
echo Saves directory: !SAVES_DIR!
echo Teams folder:    !SAVES_DIR!\teams
echo Team files found: %TEAM_COUNT%
echo Output folder:   !SAVES_DIR!\character_sheets
echo.
echo Starting character sheet generation...
echo ============================================================
echo.

REM Run the Python script with the saves directory as argument
python character_sheet_generator.py "!SAVES_DIR!"

if errorlevel 1 (
    echo.
    echo ============================================================
    echo Error: Character sheet generation failed
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo SUCCESS: Character sheets generated!
echo ============================================================
echo.
echo Opening output folder...

REM Open the output folder in Windows Explorer
start "" "!SAVES_DIR!\character_sheets"

echo.
echo Window will close in 10 seconds...
timeout /t 10 /nobreak

exit /b 0
