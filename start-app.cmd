@echo off
REM ============================================================
REM  Wakanda Forever  -  doble-clic para abrir la plataforma
REM ============================================================
title Wakanda Forever
cd /d "%~dp0"

echo.
echo   Iniciando Wakanda Forever, Norman...
echo   El navegador se abrira solo en unos segundos.
echo   (Deja esta ventana abierta mientras uses la app.)
echo.

REM Cierra cualquier servidor viejo que ocupe el puerto 8000, para que SIEMPRE
REM arranque con el codigo mas reciente (evita quedarse pegado en una version vieja).
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

REM Abre el navegador tras 3s sin bloquear el servidor.
start "" /b powershell -NoProfile -Command "Start-Sleep 3; Start-Process 'http://127.0.0.1:8000'"

REM Arranca el servidor (Ctrl+C o cerrar la ventana para detener).
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000

echo.
echo   Wakanda Forever se detuvo. Puedes cerrar esta ventana.
pause >nul
