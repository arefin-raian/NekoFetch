@echo off
REM ============================================================
REM  NekoFetch launcher (Windows)
REM  Double-click this file, or run `run.bat` from a terminal.
REM  Creates the venv + installs deps on first run, then boots
REM  the bot worker (python -m nekofetch).
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

REM --- first run: build the virtual environment ---------------
if not exist "%VENV_PY%" (
    echo [NekoFetch] No virtual environment found. Creating .venv ...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%VENV_PY%" (
        echo [NekoFetch] ERROR: could not create a virtual environment.
        echo [NekoFetch] Install Python 3.12+ from https://python.org and retry.
        pause
        exit /b 1
    )
    echo [NekoFetch] Installing dependencies ^(this runs once^) ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -e .
    if errorlevel 1 (
        echo [NekoFetch] ERROR: dependency install failed. See the output above.
        pause
        exit /b 1
    )
)

REM --- sanity: secrets file -----------------------------------
if not exist ".env" (
    echo [NekoFetch] WARNING: .env not found.
    echo [NekoFetch] Copy .env.example to .env and fill in your tokens before the bot can start:
    echo [NekoFetch]     copy .env.example .env
    echo.
)

REM --- run ----------------------------------------------------
echo [NekoFetch] Starting... ^(press Ctrl+C to stop^)
"%VENV_PY%" -m nekofetch

echo.
echo [NekoFetch] Process exited.
pause
