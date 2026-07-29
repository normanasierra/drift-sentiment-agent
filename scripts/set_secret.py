"""Set/rotate ONE secret in .env without it ever showing on screen.

Use this after regenerating a key (Render API key, Schwab App Secret, etc.) so the
NEW value goes straight into .env via a HIDDEN prompt — it never appears in the
terminal, in your shell history, or in a chat. Backs up .env first.

Run:
    .venv/bin/python scripts/set_secret.py RENDER_API_KEY        # Mac / Linux
    .venv\\Scripts\\python.exe scripts\\set_secret.py RENDER_API_KEY   # Windows

Then paste the new value at the hidden prompt and press Enter.
"""

from __future__ import annotations

import getpass
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"


def set_secret(name: str) -> None:
    if not name or "=" in name or " " in name:
        sys.exit(f"Nombre de variable inválido: {name!r}")

    if not ENV.exists():
        ENV.write_text("", encoding="utf-8")

    new = getpass.getpass(f"Pega el nuevo valor de {name} (no se ve): ").strip()
    if not new:
        sys.exit("Vacío — no cambié nada.")
    if len(new) < 8:
        sys.exit(f"Muy corto ({len(new)} chars) — ¿seguro que pegaste el valor completo?")
    confirm = input(
        f"→ {name}: empieza '{new[:3]}' … termina '{new[-3:]}' "
        f"({len(new)} caracteres). ¿Correcto? [Enter=sí / 'no']: "
    ).strip().lower()
    if confirm in ("no", "n"):
        sys.exit("Cancelado. Vuelve a correrlo.")

    # Back up before touching it.
    backup = ENV.parent / ".env.bak"
    if ENV.stat().st_size:
        shutil.copy2(ENV, backup)

    lines = ENV.read_text(encoding="utf-8").splitlines()
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(f"{name}="):
            out.append(f"{name}={new}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{name}={new}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")

    action = "actualizado" if found else "agregado"
    print(f"✅ {name} {action} en {ENV} (respaldo en .env.bak). El valor nunca se mostró.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python scripts/set_secret.py NOMBRE_DE_LA_VARIABLE")
    set_secret(sys.argv[1])
