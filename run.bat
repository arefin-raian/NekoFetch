@echo off
REM ============================================================
REM  NekoFetch launcher (Windows)
REM  Double-click this file, or run `run.bat` from a terminal.
REM  Creates the venv + installs deps on first run (or after a
REM  failed/partial install), then boots the bot worker.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

REM --- ensure a virtual environment exists --------------------
if not exist "%VENV_PY%" (
    echo [NekoFetch] No virtual environment found. Creating .venv ...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%VENV_PY%" (
        echo [NekoFetch] ERROR: could not create a virtual environment.
        echo [NekoFetch] Install Python 3.12+ from https://python.org and retry.
        pause
        exit /b 1
    )
)

REM --- ensure deps are installed ------------------------------
REM We check whether the package actually imports rather than just
REM trusting that the .venv folder exists, so a previously failed or
REM partial install is repaired automatically on the next run.
"%VENV_PY%" -c "import nekofetch" >nul 2>&1
if errorlevel 1 (
    echo [NekoFetch] Installing dependencies ^(this runs once^) ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -e .
    if errorlevel 1 (
        echo [NekoFetch] ERROR: dependency install failed. See the output above.
        pause
        exit /b 1
    )
    REM Optional native speedup ^(TgCrypto^). Needs a C compiler, so it is best-effort:
    REM a failure here is harmless — Pyrogram falls back to pure-Python crypto.
    "%VENV_PY%" -m pip install -e ".[speedups]" >nul 2>&1 && (
        echo [NekoFetch] TgCrypto speedup installed.
    ) || (
        echo [NekoFetch] TgCrypto speedup skipped ^(no C compiler^) — running without it is fine.
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
