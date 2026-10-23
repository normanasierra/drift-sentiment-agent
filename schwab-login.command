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

# macOS needs admin to open the 127.0.0.1:443 callback port (ports <1024). Windows does not.
# sudo binds the local server; the browser (your user) still reaches it — paste the URL below if
# it doesn't auto-open under sudo.
if [ "$(uname)" = "Darwin" ]; then
  echo "  NOTA (Mac): el puerto local 443 pide permiso de admin -> te pedira tu contrasena (sudo)."
  echo "  Es seguro. Si el navegador no abre solo, copia/pega en Safari/Chrome la URL que saldra abajo."
  echo ""
  sudo "$PY" scripts/schwab_auto_login.py
else
  "$PY" scripts/schwab_auto_login.py
fi

echo ""
echo "  (Puedes cerrar esta ventana.)"
