"""Fetch and summarize the day's most important market news via the Claude API.

Uses Claude with the server-side web_search tool to research and synthesize the
morning market picture (Fed, wars, oil, notable stocks, politics — with an
explicit eye on anything Trump says on any platform).

This is the only LLM-backed step; everything else in daily_report is
deterministic. It degrades gracefully: if the `anthropic` package or an API
credential is missing, `fetch_news()` returns "" and the runner simply omits
the news section rather than failing the whole report.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-4-8"

NEWS_PROMPT = """You are a market-desk analyst writing a pre-market brief for a
US options trader. Using web search, find TODAY's most important, market-moving
news and summarize it tightly. Cover, in this priority order:

1. The Federal Reserve — rate decisions, speeches, minutes, dot-plot, any FOMC
   member commentary, inflation/jobs prints that move rate expectations.
2. Wars / geopolitics — active conflicts, escalations, sanctions, anything
   moving risk sentiment or defense names.
3. Oil & energy — crude price moves and their drivers (OPEC, supply, demand).
4. Notable single stocks — mega-caps and semis (AAPL MSFT GOOGL AMZN NVDA META
   TSLA AMD MU INTC MRVL), earnings, guidance, analyst moves, big gaps.
5. Politics — especially ANYTHING Trump has said today on any platform (Truth
   Social, X, interviews, rallies, official statements) that could move markets:
   tariffs, the Fed, taxes, specific companies or sectors.

Preferred sources: CNBC, Barron's, Yahoo Finance, Reuters, Bloomberg, WSJ, and
official Fed / White House / Truth Social / X posts. Weight reputable financial
press; verify Trump quotes against a primary source before including them.

Rules:
- Only include items from the last ~24-48 hours. Skip stale/background context.
- Be concise: short bullets, lead with the ticker/entity, then the fact, then
  why it matters for markets in a few words.
- Group under headers: FED / GEOPOLITICS / OIL / STOCKS / TRUMP & POLITICS.
- If a category has nothing fresh, write "nothing material today".
- No preamble, no disclaimer — just the brief.
"""


def fetch_news(*, max_tokens: int = 4000) -> str:
    """Return a plain-text market-news brief, or "" if unavailable."""
    try:
        import anthropic
    except ImportError:
        return ""

    # Anthropic() resolves ANTHROPIC_API_KEY / auth token / profile itself; if
    # nothing is configured it raises, which we swallow to keep the report alive.
    try:
        client = anthropic.Anthropic()
    except Exception:
        return ""

    tools = [{"type": "web_search_20260209", "name": "web_search"}]
    messages = [{"role": "user", "content": NEWS_PROMPT}]

    try:
        # Stream to avoid HTTP timeouts on a long, tool-using turn.
        for _ in range(6):  # bound the server-tool pause/continue loop
            with client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                tools=tools,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()

            if response.stop_reason == "pause_turn":
                # Server tool hit its iteration limit — resend to resume.
                messages = [
                    {"role": "user", "content": NEWS_PROMPT},
                    {"role": "assistant", "content": response.content},
                ]
                continue
            break

        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return text
    except Exception as exc:  # noqa: BLE001 — news is best-effort
        return f"(news step failed: {exc})"


if __name__ == "__main__":
    print(fetch_news() or "(no news — check ANTHROPIC_API_KEY / anthropic install)")
