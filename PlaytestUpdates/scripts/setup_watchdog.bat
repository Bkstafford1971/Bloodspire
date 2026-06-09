@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ================================================================
echo     BLOODSPIRE Server Watchdog Setup
echo  ================================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: This script must be run as Administrator.
    echo  Right-click setup_watchdog.bat and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

set TASK=BloodspireServerWatchdog
set PSFILE=%~dp0watchdog.ps1
set PSCMD=powershell.exe -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "%PSFILE%"

echo  Removing any existing watchdog task...
schtasks /delete /tn "%TASK%" /f >nul 2>&1

echo  Registering watchdog task (every 5 minutes, runs as SYSTEM)...
schtasks /create /tn "%TASK%" /tr "%PSCMD%" /sc MINUTE /mo 5 /ru SYSTEM /rl HIGHEST /f >nul

if %errorlevel% neq 0 (
    echo.
    echo  Failed to register the task. Make sure you are running as Administrator.
    echo.
    pause
    exit /b 1
)

echo  Task registered successfully.
echo.
echo  Capabilities:
echo    - Checks the server every 5 minutes
echo    - Restarts it automatically if it stops responding
echo    - Logs all restarts to:  %~dp0watchdog.log
echo.
echo  Useful commands:
echo    Run now   : schtasks /run /tn %TASK%
echo    View log  : notepad "%~dp0watchdog.log"
echo    Remove    : schtasks /delete /tn %TASK% /f
echo.

echo  Running watchdog once now to verify...
schtasks /run /tn "%TASK%"
timeout /t 6 /nobreak >nul

if exist "%~dp0watchdog.log" (
    echo  Watchdog is working. Log:
    echo.
    type "%~dp0watchdog.log"
) else (
    echo  Server was already running - no restart needed.
)

echo.
pause
