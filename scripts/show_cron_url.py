"""Print the cron-job.org setup for the 3x/day cloud brief — locally, so the secret
TASKS_KEY never goes through a chat. Reads TASKS_KEY from Render (needs RENDER_API_KEY
+ RENDER_SERVICE_ID in .env) and prints the trigger URL + the recommended schedule.

Run:  .venv/bin/python scripts/show_cron_url.py
Then create 3 cron jobs at https://cron-job.org with the URL and the times below.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
API = "https://api.render.com/v1"
APP = "https://drift-sentiment-web.onrender.com"


def main() -> None:
    key = os.getenv("RENDER_API_KEY")
    sid = os.getenv("RENDER_SERVICE_ID")
    if not (key and sid):
        raise SystemExit("Falta RENDER_API_KEY / RENDER_SERVICE_ID en .env.")
    ev = requests.get(f"{API}/services/{sid}/env-vars?limit=100",
                      headers={"Authorization": f"Bearer {key}"}, timeout=20).json()
    tk = next((e["envVar"]["value"] for e in ev if e["envVar"]["key"] == "TASKS_KEY"), None)
    if not tk:
        raise SystemExit("No hay TASKS_KEY en Render.")

    url = f"{APP}/tasks/run?job=brief&key={tk}"
    print("\n=== CONFIGURACIÓN cron-job.org (crea 3 cron jobs) ===\n")
    print("URL (la MISMA para los 3 — pégala en 'URL' del cron job):")
    print(f"  {url}\n")
    print("Zona horaria (Timezone) en cron-job.org:  America/New_York")
    print("(así sigue solo el horario del mercado aunque cambie el horario de verano)\n")
    print("Los 3 horarios (días: Lunes a Viernes):")
    print("  1) ANTES de abrir   ->  08:30")
    print("  2) DURANTE          ->  12:00")
    print("  3) DESPUÉS de cerrar->  16:15\n")
    print("Método: GET.  Todo lo demás por defecto.  Guarda cada uno y listo.\n")


if __name__ == "__main__":
    main()
