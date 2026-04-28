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

:: Cloudflare R2 Credentials
:: IMPORTANT: Replace the values below. If your keys contain special characters, 
:: the quotes around the values will ensure they are read correctly.
set "R2_ACCESS_KEY_ID=13412fe25063db3a54b481c6293629dd"
set "R2_SECRET_ACCESS_KEY=45a9cb21bf6c0b3b207509f8ae2311c09478a88cfd9a85aa0fd1a6abb2739376"
set "R2_ENDPOINT_URL=https://cbb02655e8f8c8a15fe95a8eaf5aa8f5.r2.cloudflarestorage.com"

echo  Checking R2 configuration...

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
python league_server.py --host-password "%HOST_PW%"

echo. 
echo  Server has stopped.
pause