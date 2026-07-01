@echo off
REM =============================================================================
REM Warrior Strategy Optimizer Launcher
REM =============================================================================

cd /d "%~dp0"

echo.
echo ============================================================================
echo   BLOODSPIRE WARRIOR STRATEGY OPTIMIZER
echo ============================================================================
echo.

python warrior_strategy_optimizer.py

if errorlevel 1 (
    echo.
    echo ERROR: Strategy optimizer failed to run.
    echo Make sure Python is installed and in your PATH.
    echo.
    pause
)
