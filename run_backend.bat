@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%ROOT%.env" (
    copy "%ROOT%.env.example" "%ROOT%.env" >nul
    echo Created .env from .env.example
    echo Edit .env and run again.
    exit /b 1
)

if not exist "%VENV_PY%" (
    py -3.13 -m venv "%VENV_DIR%" 2>nul || python -m venv "%VENV_DIR%"
)

if not exist "%VENV_PY%" (
    echo Failed to create .venv. Install Python 3.11+ and retry.
    exit /b 1
)

call "%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip >nul
call "%VENV_PY%" -m pip install --disable-pip-version-check -r "%ROOT%backend\requirements.txt"
if errorlevel 1 exit /b 1

cd /d "%ROOT%backend"
"%VENV_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
