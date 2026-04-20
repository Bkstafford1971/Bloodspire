@echo off
chcp 65001 >nul
title BLOODSPIRE - Tailscale Setup
cls

echo.
echo  ================================================================
echo     BLOODSPIRE - TAILSCALE INSTALLATION HELPER
echo  ================================================================
echo.
echo  Tailscale is required to connect to the league server.
echo  This script will help you install it.
echo.
echo  You will need administrator privileges to install Tailscale.
echo.

:check_admin
net session >nul 2>&1
if %errorLevel% == 0 (
    echo  ✓ Running as administrator
) else (
    echo  ✗ Administrator privileges required. Please right-click this
    echo    batch file and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

echo.
echo  Downloading Tailscale installer...
echo.

:: Download Tailscale MSI installer
powershell -Command "& {Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' -OutFile '%TEMP%\tailscale-setup.exe'}"

if not exist "%TEMP%\tailscale-setup.exe" (
    echo  ✗ Failed to download Tailscale installer.
    echo.
    echo  Please download it manually from:
    echo  https://tailscale.com/download
    echo.
    pause
    exit /b 1
)

echo  ✓ Download complete.
echo.
echo  Installing Tailscale...
echo.

:: Run the installer
"%TEMP%\tailscale-setup.exe" /quiet /norestart

echo.
echo  Tailscale installation initiated.
echo.
echo  After installation completes:
echo  1. Open Tailscale from the system tray
echo  2. Sign in with your preferred method
echo  3. You should then be able to connect to the league server
echo.
echo  Press any key to continue...
pause >nul

echo.
echo  Cleaning up temporary files...
del "%TEMP%\tailscale-setup.exe" 2>nul

echo  ✓ Setup complete. You can now run START_GAME.bat
echo.
pause