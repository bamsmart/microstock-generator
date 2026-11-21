@echo off
rem ==============================================================================
rem Microstock Generator - Windows 1-Click Launcher (Command Prompt / Batch)
rem ==============================================================================

setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

rem 1. Detect System Python
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "SYS_PYTHON=python"
) else (
    where py >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        set "SYS_PYTHON=py -3"
    ) else (
        echo [ERROR] Python 3 was not found on your system.
        echo Please download and install Python 3.10+ from https://www.python.org/
        echo (Make sure to check "Add Python to PATH" during installation)
        echo.
        pause
        exit /b 1
    )
)

rem 2. Detect and self-heal virtual environment if broken
set RECREATE_VENV=0
if not exist "%SCRIPT_DIR%.venv\" (
    if not exist "%SCRIPT_DIR%venv\" (
        set RECREATE_VENV=1
    )
) else (
    if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
        "%SCRIPT_DIR%.venv\Scripts\python.exe" -c "import sys" >nul 2>nul
        if !ERRORLEVEL! neq 0 (
            echo [WARNING] Stale or invalid virtual environment detected. Self-healing...
            rmdir /s /q "%SCRIPT_DIR%.venv"
            set RECREATE_VENV=1
        )
    )
)

if !RECREATE_VENV! equ 1 (
    echo ==================================================
    echo [SETUP] Creating Python Virtual Environment...
    echo ==================================================
    %SYS_PYTHON% -m venv "%SCRIPT_DIR%.venv"
    "%SCRIPT_DIR%.venv\Scripts\python.exe" -m pip install --upgrade pip
    if exist "%SCRIPT_DIR%requirements.txt" (
        echo [SETUP] Installing required dependencies...
        "%SCRIPT_DIR%.venv\Scripts\python.exe" -m pip install -r "%SCRIPT_DIR%requirements.txt"
    )
    echo [SETUP] Installation complete!
    echo.
)

rem 3. Select virtualenv Python binary
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON_BIN=%SCRIPT_DIR%venv\Scripts\python.exe"
) else (
    set "PYTHON_BIN=%SYS_PYTHON%"
)

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
chcp 65001 >nul

%PYTHON_BIN% "%SCRIPT_DIR%main.py" %*

echo.
pause
