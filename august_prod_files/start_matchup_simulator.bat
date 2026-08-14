@echo off
REM Start the Matchup Simulator App
cd /d "%~dp0"
echo Installing required dependencies...
pip install flask openpyxl
echo.
echo Starting Matchup Simulator App...
python matchup_simulator_app.py
