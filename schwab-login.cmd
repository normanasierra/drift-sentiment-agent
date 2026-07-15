@echo off
REM ============================================================
REM  Schwab Login (READ-ONLY) - auto-captura, sin copiar-pegar
REM ============================================================
title Schwab Login (solo lectura)
cd /d "%~dp0"

echo.
echo   AUTORIZACION DE SCHWAB (solo lectura). Casi automatico:
echo.
echo   1. Se abre Schwab: inicia sesion y dale APPROVE / DONE.
echo   2. Saldra una advertencia de seguridad de 127.0.0.1 (por el
echo      certificado local). Dale:
echo        Chrome/Edge: "Configuracion avanzada" -^> "Continuar a 127.0.0.1".
echo      Es SEGURO: es TU propia maquina.
echo   3. Y ya: yo capturo el codigo y guardo el token solo.
echo.

".venv\Scripts\python.exe" scripts\schwab_auto_login.py

echo.
echo   (Puedes cerrar esta ventana.)
pause >nul
