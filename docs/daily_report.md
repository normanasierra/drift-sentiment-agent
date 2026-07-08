# Daily 9AM Market Report

Automated pre-market brief delivered every day at 9:00 AM by **email** (full
report) and **WhatsApp** (highlights). Three parts:

1. **News** — Fed, wars, oil, notable stocks, and politics (with an explicit eye
   on anything Trump says on any platform), researched live via Claude + web
   search.
2. **Analysis** — entries/exits + magnetos (GEX) at **30 / 90 / 120 / 320 DTE**
   (20-day tolerance) for the ticker universe.
3. **Delivery** — email via SMTP, WhatsApp via Twilio.

## Ticker universe

Magnificent 7 (AAPL MSFT GOOGL AMZN NVDA META TSLA) + **SPY** (free-tier proxy
for SPX — SPX itself returns no spot on the Polygon free tier) + AMD, MU, INTC,
MRVL. Edit `daily_report/config.py` to change.

## One-time setup

### 1. Credentials — fill in `.env`

Copy `.env.example` → `.env` and fill in:

| Section  | Vars | How to get it |
|----------|------|---------------|
| Market   | `POLYGON_API_KEY` | already set |
| Email    | `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | Gmail → [App Passwords](https://myaccount.google.com/apppasswords) (needs 2FA on). `SMTP_PASSWORD` is the 16-char app password, **not** your login password. |
| WhatsApp | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_TO` | [Twilio Console](https://console.twilio.com/) → Messaging → WhatsApp. The sandbox is free for testing; join it from your phone first. |
| News     | `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/). Optional — without it the report still sends, just without the news section. |

### 2. Install the scheduler (macOS launchd)

```sh
cp scripts/com.drift.dailyreport.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.drift.dailyreport.plist
```

The Mac must be awake at 9am for the job to fire. If asleep, it runs on next
wake (or set a `pmset` wake schedule).

## Testing

```sh
# Full pipeline, print instead of send (no news, no API cost):
.venv/bin/python -m daily_report.run --no-news --dry-run

# Analysis only, one ticker, to stdout:
.venv/bin/python -m daily_report.analyze --tickers AMD

# Just the news step:
.venv/bin/python -m daily_report.news

# Send for real, right now:
.venv/bin/python -m daily_report.run          # email + whatsapp
.venv/bin/python -m daily_report.run --no-whatsapp   # email only

# Trigger the scheduled job by hand:
launchctl start com.drift.dailyreport
```

Run logs land in `output/daily_report-*.log`.

## Notes & limits

- **Polygon free tier** is rate-limited; the run throttles between tickers and
  retries on HTTP 429. 12 tickers take a few minutes.
- **WhatsApp** body is truncated to ~1500 chars (Twilio limit) — the full detail
  is always in the email.
- **DTE fallback**: if a ticker's longest monthly is short of the 320-DTE target
  (common), that bucket is flagged `*` / "FALLBACK, out of tolerance".
- **Portfolio photo review** is a separate, manual flow — send the photo in
  chat and it gets reviewed for entries/closes/magnetos; the 9am cron can't wait
  on an image.
