@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"

cd /d "%ROOT%frontend"
call npm install
if errorlevel 1 exit /b 1

echo Starting frontend on http://127.0.0.1:%FRONTEND_PORT%
call npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%
