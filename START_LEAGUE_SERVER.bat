@echo off
chcp 65001 >nul
title BLOODSPIRE League Server
cls

echo.
echo  ================================================================
echo     BLOODSPIRE LEAGUE SERVER
echo  ================================================================
echo.
echo  This starts the multiplayer league server that other players
echo  can connect to. You still run START_GAME.bat to play yourself.
echo.

:: Host password — hardcoded to "password" for testing.
:: To require a prompt again, comment this out and uncomment the block below.
set HOST_PW=password

REM set /p HOST_PW="  Enter a host/admin password for the league server: "
REM if "%HOST_PW%"=="" (
REM     echo.
REM     echo  ERROR: Password cannot be blank.
REM     echo.
REM     pause
REM     exit /b 1
REM )

echo  Using test host password: %HOST_PW%

cls
echo.
echo  Starting league server on port 8766...
echo  Keep this window open while players are connected.
echo  Press Ctrl+C to stop the server.
echo.

:: Get current turn number
for /f "tokens=*" %%a in ('python -c "import json, os; f='saves/league/config.json'; print(json.load(open(f))['current_turn'] if os.path.exists(f) else '—')" 2^>nul') do set CURRENT_TURN=%%a

REM echo  ╔══════════════════════════════════════════════╗
REM echo  ║          BLOODSPIRE LEAGUE SERVER            ║
REM echo  ╚══════════════════════════════════════════════╝
REM echo.
REM echo  Admin panel :  http://localhost:8766/admin
REM echo  Player URL  :  http://YOUR_LAN_IP:8766
REM echo  Current turn: %CURRENT_TURN%
REM echo.
REM echo  ⚠  Share your LAN or public IP (not 'localhost') with other players.
REM echo  ⚠  Forward port 8766 on your router if players are connecting from outside.
REM echo.

cd /d "%~dp0"

:run
python league_server.py --host-password "%HOST_PW%"
set EXIT_CODE=%errorlevel%

:: Exit code 0 = intentional shutdown (Ctrl+C). Stop here.
if %EXIT_CODE%==0 (
    echo.
    echo  Server stopped normally.
    pause
    exit /b 0
)

:: Non-zero = unexpected crash. Auto-restart after a short delay.
echo.
echo  !! Server crashed (exit code %EXIT_CODE%). Restarting in 15 seconds...
echo     Press Ctrl+C now to cancel restart.
echo.
timeout /t 15 /nobreak >nul
goto run