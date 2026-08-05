#!/bin/bash
# ============================================================
#  Schwab re-auth on the MAC (READ-ONLY) — manual copy/paste.
# ============================================================
# Use this ONLY while traveling with the PC OFF, to renew the Schwab token so the
# CLOUD brief keeps its break-even table past the ~7-day expiry.
#
# Unlike the Windows auto-login, this flow needs NO local certificate and NO admin
# (it doesn't bind port 443) — it just exchanges the redirect code you paste and then
# pushes the fresh token to Render automatically.
#
# GOLDEN RULE: normally you re-auth on the PC, never the Mac (Schwab issues ONE refresh
# token per app). This is safe here ONLY because the PC is off during the trip — when you
# get back, re-auth on the PC as usual and it becomes master again.
#
# First run: if macOS blocks it, right-click the file -> Open.

cd "$(dirname "$0")" || exit 1
PY="./.venv/bin/python3"
[ -x "$PY" ] || PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "=== Schwab re-auth (Mac, manual copy/paste — READ-ONLY) ==="
echo ""

# Pre-check: the fresh token only reaches the CLOUD brief if these are in the Mac's .env.
"$PY" - <<'PYEOF'
import os
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass
need = ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "RENDER_API_KEY", "RENDER_SERVICE_ID"]
missing = [k for k in need if not os.getenv(k)]
if missing:
    print("AVISO: faltan estas llaves en el .env del Mac: " + ", ".join(missing))
    print("Sin RENDER_API_KEY / RENDER_SERVICE_ID el token se guarda LOCAL pero NO llega")
    print("a la nube, y el brief en la nube seguira sin break-even. Agregalas y reintenta.")
else:
    print("Config OK: al terminar, el token fresco se empuja a la nube (Render).")
PYEOF

echo ""
"$PY" scripts/schwab_auth.py
echo ""
read -n 1 -s -r -p "Listo. Presiona una tecla para cerrar esta ventana."
echo ""
