@echo off
chcp 65001 >nul
title BLOODSPIRE
cls
setlocal

set "APP_DIR=%~dp0"
set "PORTABLE_PYTHON=%APP_DIR%PortablePython\python.exe"
if not exist "%PORTABLE_PYTHON%" set "PORTABLE_PYTHON=%APP_DIR%PythonPortable\python.exe"

echo.
echo  ================================================================
echo     BLOODSPIRE CLIENT
echo  ================================================================
echo.
echo  Starting BLOODSPIRE...
echo  Your browser will open automatically.
echo  Keep this window open while playing.
echo  Press Ctrl+C in this window to stop the server.
echo.

if exist "%PORTABLE_PYTHON%" (
    "%PORTABLE_PYTHON%" --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  ERROR: Bundled portable Python is invalid or too old.
        echo  Please update the portable Python distribution in "%APP_DIR%PortablePython".
        echo.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=%PORTABLE_PYTHON%"
) else (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  ERROR: Python is not installed or not in your PATH.
        echo.
        echo  Please install Python 3.8 or newer, or place a portable Python distro in:
        echo  %APP_DIR%PortablePython\python.exe
        echo.
        pause
        exit /b 1
    )

    python -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  ERROR: Python 3.8 or newer is required.
        echo  Please update Python from https://www.python.org/downloads/.
        echo.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python.exe"
)

echo.
echo  Server running at: http://localhost:8765
echo  Opening browser... (Ctrl+C to stop)
echo.

cd /d "%APP_DIR%"
"%PYTHON_EXE%" gui_server.py

echo.
echo  Server has stopped.
endlocal
REM pause