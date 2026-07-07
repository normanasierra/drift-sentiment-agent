# Daily market brief

Automated 9:00 AM (local, UTC−04) market brief, Monday–Friday:

- **Full analysis → email** (Gmail SMTP)
- **Key points → WhatsApp** (CallMeBot)

Scope: US indices + macro (SPY/QQQ, VIX, rates, top macro headlines).
Educational only — **not financial advice**.

## Pieces

| File | Role |
|------|------|
| `send_email.py` | Sends the full brief by email. Reads Gmail creds from `.env`. |
| `send_whatsapp.py` | Sends the key points to WhatsApp via CallMeBot. |
| `../../.env` | Holds all secrets (gitignored — never commit). |

The analysis itself is produced by Claude at run time (web search for news +
market data), then piped into these two senders.

## One-time setup

### 1. Gmail App Password (for email)

1. Enable 2-Step Verification on your Google account (required for app passwords).
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password (name it e.g. "drift-brief"). Google shows a 16-char code.
4. Put it in `.env` (remove the spaces):

   ```
   GMAIL_USER=normanasierra@gmail.com
   GMAIL_APP_PASSWORD=abcdefghijklmnop
   BRIEF_EMAIL_TO=normanasierra@gmail.com
   ```

### 2. CallMeBot (for WhatsApp)

1. Save **+34 644 51 95 23** to your phone contacts (name it "CallMeBot").
2. From WhatsApp, send that contact: `I allow callmebot to send me messages`
3. It replies with **your personal API key** (usually within a minute).
4. Put your number + key in `.env`:

   ```
   CALLMEBOT_PHONE=+591XXXXXXXX
   CALLMEBOT_APIKEY=123456
   ```

## Test the senders (once `.env` is filled)

```bash
# Email
echo "Test brief body" | .venv/Scripts/python scripts/daily_brief/send_email.py --subject "Test"

# WhatsApp
echo "Test key point" | .venv/Scripts/python scripts/daily_brief/send_whatsapp.py
```

If both arrive, the delivery layer works and we can wire up the 9 AM schedule.
