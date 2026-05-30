@echo off
REM ============================================================
REM Arranque local del backend Python retail-ai-platform.
REM Doble click sobre este archivo abre una ventana persistente
REM con uvicorn escuchando en localhost:8001.
REM Cerrar con Ctrl+C o cerrando la ventana.
REM ============================================================

setlocal
set "API_DIR=%~dp0api"
set "PY=%API_DIR%\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] No se encontro el venv en %API_DIR%\.venv
    echo Crear con: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

cd /d "%API_DIR%"
echo Iniciando uvicorn en http://localhost:8001 ...
echo Logs en esta ventana. Ctrl+C para detener.
echo.
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8001
