@echo off
REM Batch file to run the BPClone simulation tool
REM Changes to the script directory and runs simulation_tool.py

cd /d "%~dp0"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.7+ or add it to your system PATH
    pause
    exit /b 1
)

REM Run the simulation tool
python simulation_tool.py

REM Pause if there was an error so user can see the message
if errorlevel 1 (
    echo.
    echo An error occurred running the simulation tool.
    pause
)
