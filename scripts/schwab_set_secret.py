"""Update just the Schwab App Secret in .env (after regenerating it on
developer.schwab.com), then clear old tokens so the next login re-auths cleanly.

Robust against the cmd terminal duplicating a paste: it AUTO-de-duplicates the
pasted value and confirms the length before saving. READ-ONLY app — no trading.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _base_unit(x: str) -> str:
    """Smallest repeating unit — undoes a duplicated paste (secret x N -> secret)."""
    for n in range(1, len(x) + 1):
        if len(x) % n == 0 and x[:n] * (len(x) // n) == x:
            return x[:n]
    return x


def main() -> None:
    print("=== Actualizar App Secret de Schwab ===")
    print("Pega el NUEVO Secret (el que acabas de regenerar). No se ve al escribir.\n")
    raw = getpass.getpass("   Nuevo App Secret: ").strip()
    sec = _base_unit(raw)  # auto-fix a duplicated paste
    low = sec.lower()
    if not sec or "=" in sec or " " in sec or "http" in low or "://" in low or len(sec) < 12:
        sys.exit("Eso no parece un Secret válido (URL, vacío o muy corto). Reintenta.")

    print(f"\n   Secret detectado: empieza '{sec[:4]}' … termina '{sec[-4:]}' ({len(sec)} caracteres).")
    if raw != sec:
        print(f"   (Se pegó duplicado {len(raw)}→{len(sec)} chars; lo corregí solo.)")
    ans = input("   ¿Correcto? [Enter=sí / 'no'=cancelar]: ").strip().lower()
    if ans not in ("", "s", "si", "sí", "y", "yes", "ok"):
        sys.exit("Cancelado. Corre de nuevo cuando quieras.")

    env = REPO / ".env"
    lines = [l for l in env.read_text(encoding="utf-8").splitlines()
             if not l.strip().startswith("SCHWAB_APP_SECRET=")]
    lines.append(f"SCHWAB_APP_SECRET={sec}")
    env.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")

    # Old tokens were minted with the OLD secret — drop them so the next login
    # gets a clean, fresh set with the new secret.
    try:
        (REPO / "output" / "schwab_tokens.json").unlink()
    except FileNotFoundError:
        pass

    print("\n✅ Secret actualizado en .env y tokens viejos borrados.")
    print("   Ahora doble-clic a schwab-login.cmd para re-autorizar (1 clic).")


if __name__ == "__main__":
    main()
