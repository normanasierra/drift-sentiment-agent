#!/bin/bash
# =============================================================
#  Schwab Login (READ-ONLY) for the Mac — auto-capture, no copy/paste.
#  Norman runs this during travel to refresh the ~7-day Schwab token.
#  It saves the token locally AND auto-pushes it to Render (the cloud brief),
#  so positions + the break-even table keep working while away.
#  (Double-click in Finder, or run:  bash schwab-login.command)
# =============================================================
cd "$(dirname "$0")" || exit 1

echo ""
echo "  AUTORIZACION DE SCHWAB (solo lectura). Casi automatico:"
echo "   1. Se abre Schwab: inicia sesion y dale APPROVE / DONE."
echo "   2. Saldra una advertencia de 127.0.0.1 (certificado local). En Safari/Chrome:"
echo "        'Mostrar detalles' -> 'visitar este sitio web' / 'Continuar a 127.0.0.1'."
echo "      Es SEGURO: es TU propia maquina."
echo "   3. Listo: capturo el codigo, guardo el token y lo empujo a Render solo."
echo ""

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
"$PY" scripts/schwab_auto_login.py

echo ""
echo "  (Puedes cerrar esta ventana.)"
