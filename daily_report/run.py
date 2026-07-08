"""End-to-end daily run: analyze the universe, assemble the report, deliver it.

Designed to be driven two ways:
  1. Standalone cron  — `python -m daily_report.run`  (analysis + delivery only).
  2. From a Claude scheduled agent that first web-researches the news and passes
     it in via `--news-file` (Fed / wars / oil / politics / Trump synthesis).

The market analysis is fully deterministic and offline of any LLM; only the
news narrative is LLM-authored when a news file is supplied.
"""

from __future__ import annotations

import argparse
import sys

from drift_sentiment import polygon_client

from . import config
from .analyze import analyze_all, full_report, whatsapp_highlights
from .send import deliver


def _read(path: str | None) -> str:
    """News source: an explicit file if given, else the live Claude+web-search step."""
    if not path:
        from .news import fetch_news
        return fetch_news()
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError as exc:
        return f"(news unavailable: {exc})"


def build_bodies(news: str, as_of: str) -> tuple[str, str, str]:
    """Return (subject, email_body, whatsapp_body)."""
    from . import portfolio

    outcomes = analyze_all()
    port_review = portfolio.review()

    subject = f"Drift Sentiment — Reporte Diario {as_of}"

    # Fold in any newsletter subjects from the inbox (MarketSnacks/Barron's/CNBC).
    try:
        from data_sources import email_inbox
        inbox = email_inbox.digest()
    except Exception:  # noqa: BLE001
        inbox = ""
    if inbox:
        news = (news + "\n\n" + inbox).strip() if news else inbox

    email_parts = [subject, ""]
    if news:
        email_parts += ["=== NOTICIAS DEL MERCADO ===", news, ""]
    email_parts += [port_review, ""]
    email_parts.append(full_report(outcomes, as_of))
    email_body = "\n".join(email_parts)

    wa_parts = [f"*Drift {as_of}*", portfolio.whatsapp_line()]
    if news:
        # First few lines of the news for the WhatsApp teaser.
        teaser = "\n".join(news.splitlines()[:6])
        wa_parts += ["", "NOTICIAS:", teaser]
    wa_parts += ["", "MAGNETOS/ENTRADAS:", whatsapp_highlights(outcomes)]
    whatsapp_body = "\n".join(wa_parts)

    return subject, email_body, whatsapp_body


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily analyze + deliver")
    ap.add_argument("--news-file", help="path to a text file with the news narrative")
    ap.add_argument("--no-news", action="store_true", help="skip the news step entirely")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-whatsapp", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    args = ap.parse_args(argv)

    as_of = polygon_client.today().isoformat()
    news = "" if args.no_news else _read(args.news_file)
    subject, email_body, whatsapp_body = build_bodies(news, as_of)

    if args.dry_run:
        print("SUBJECT:", subject)
        print("\n===== EMAIL =====\n")
        print(email_body)
        print("\n===== WHATSAPP =====\n")
        print(whatsapp_body)
        return 0

    status = deliver(
        subject,
        email_body,
        whatsapp_body,
        do_email=not args.no_email,
        do_whatsapp=not args.no_whatsapp,
    )
    for channel, result in status.items():
        print(f"{channel}: {result}")
    return 0 if all(v == "sent" for v in status.values()) else 1


if __name__ == "__main__":
    sys.exit(_main())
