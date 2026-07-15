@echo off
REM ============================================================
REM  Actualizar el App Secret de Schwab (tras regenerarlo)
REM ============================================================
title Schwab - nuevo Secret
cd /d "%~dp0"

echo.
echo   Pega tu NUEVO App Secret (el que regeneraste en developer.schwab.com).
echo   Corrige solo si se pega duplicado, y te lo confirma antes de guardar.
echo.

".venv\Scripts\python.exe" scripts\schwab_set_secret.py

echo.
echo   Cuando termine: doble-clic a schwab-login.cmd para re-autorizar.
pause >nul
