"""One-off WhatsApp nudge to run the sleep verification test tonight (before the
00:00 WeeknightSleep fires). Fired once by the RemindSleepTest scheduled task."""
import os
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
env = REPO / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

phone, key = os.getenv("CALLMEBOT_PHONE"), os.getenv("CALLMEBOT_APIKEY")
msg = ("🌙 Recuerda esta noche (antes de medianoche):\n"
       "1) Dile a Candy \"probemos el sleep\" para verificar que la máquina duerme y despierta.\n"
       "2) Dale el UPDATE a la PC (Windows Update).")
if phone and key:
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": phone, "text": msg, "apikey": key})
    try:
        urllib.request.urlopen(url, timeout=25)
    except Exception:  # noqa: BLE001
        pass
