"""US stock-market (NYSE/Nasdaq) holiday calendar — so the daily brief skips days
the market is closed. Pure stdlib; computes holidays for any year.

Handles the 10 full-day closures (New Year's, MLK, Presidents, Good Friday,
Memorial, Juneteenth, Independence, Labor, Thanksgiving, Christmas) with NYSE's
weekend-observance rule (Sat -> preceding Fri, Sun -> following Mon). Half-days
(e.g. day after Thanksgiving) are NOT treated as closed — the market is open.
"""

from __future__ import annotations

import datetime as _dt


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """n-th `weekday` (Mon=0..Sun=6) of the month."""
    first = _dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + _dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    last = (_dt.date(year, 12, 31) if month == 12
            else _dt.date(year, month + 1, 1) - _dt.timedelta(days=1))
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> _dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    p = (h + m - 7 * ((a + 11 * h + 22 * m) // 451) + 114)
    return _dt.date(year, p // 31, p % 31 + 1)


def _observed(d: _dt.date) -> _dt.date:
    """NYSE weekend observance: Saturday -> Friday, Sunday -> Monday."""
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def market_holidays(year: int) -> set[_dt.date]:
    gf = _easter(year) - _dt.timedelta(days=2)  # Good Friday
    return {
        _observed(_dt.date(year, 1, 1)),      # New Year's Day
        _nth_weekday(year, 1, 0, 3),          # MLK Day (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),          # Presidents' Day (3rd Mon Feb)
        gf,
        _last_weekday(year, 5, 0),            # Memorial Day (last Mon May)
        _observed(_dt.date(year, 6, 19)),     # Juneteenth
        _observed(_dt.date(year, 7, 4)),      # Independence Day
        _nth_weekday(year, 9, 0, 1),          # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),         # Thanksgiving (4th Thu Nov)
        _observed(_dt.date(year, 12, 25)),    # Christmas
    }


def is_market_closed(d: _dt.date | None = None) -> bool:
    """True on weekends and full-day US market holidays."""
    d = d or _dt.date.today()
    return d.weekday() >= 5 or d in market_holidays(d.year)


if __name__ == "__main__":
    for y in (2026, 2027):
        print(y, sorted(str(x) for x in market_holidays(y)))
