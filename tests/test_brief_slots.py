"""Per-slot delivery dedup helpers in run_brief_local (pure / offline)."""
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

D = Path(__file__).resolve().parents[1] / "scripts" / "daily_brief"
sys.path.insert(0, str(D))
spec = importlib.util.spec_from_file_location("run_brief_local", D / "run_brief_local.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

NY = ZoneInfo("America/New_York")


def _at(h, m, tz=NY, d=(2026, 11, 5)):
    return dt.datetime(*d, h, m, tzinfo=tz)


def test_labels_and_subjects():
    assert [rb._slot_label(s) for s in rb.SLOTS] == [
        "8:30 AM", "10:30 AM", "12:00 PM", "3:00 PM", "4:30 PM"]
    sub = rb._subject_for("Brief de Mercado", _at(8, 20), "0830")
    assert sub == "Brief de Mercado - 11/05/2026 (8:30 AM)"
    # five distinct keys → dedup of one slot can never block another
    assert len({rb._subject_for("Brief de Mercado", _at(9, 0), s) for s in rb.SLOTS}) == 5
    # legacy (Cierre / Sunday) subject unchanged
    assert rb._subject_for("Cierre de Mercado", _at(17, 0), None) == "Cierre de Mercado - 11/05/2026"


def test_slot_window():
    ok, d = rb._slot_timing("0830", _at(8, 20))      # fired 10 min early → fine
    assert ok and d == -10
    assert rb._slot_timing("0830", _at(8, 50))[0]    # a bit late → fine
    assert not rb._slot_timing("0830", _at(7, 45))[0]   # wrong-zone twin trigger (1h early) → no-op
    assert not rb._slot_timing("0830", _at(10, 0))[0]   # stale → skip
    assert not rb._slot_timing("1630", _at(15, 20))[0]


def test_tz_switch_on_nov_9(monkeypatch):
    monkeypatch.delenv("BRIEF_TZ", raising=False)
    assert rb._brief_tz_name(dt.date(2026, 11, 8)) == "America/New_York"
    assert rb._brief_tz_name(dt.date(2026, 11, 9)) == "America/Puerto_Rico"
    monkeypatch.setenv("BRIEF_TZ", "America/Chicago")
    assert rb._brief_tz_name(dt.date(2026, 11, 9)) == "America/Chicago"


def test_same_wallclock_fires_both_utc_twins():
    """8:20 local = 13:20 UTC (EST) or 12:20 UTC (AST): exactly one of the two UTC triggers is in-window."""
    est_now = dt.datetime(2026, 11, 5, 13, 20, tzinfo=dt.timezone.utc).astimezone(NY)
    twin = dt.datetime(2026, 11, 5, 12, 20, tzinfo=dt.timezone.utc).astimezone(NY)
    assert rb._slot_timing("0830", est_now)[0] and not rb._slot_timing("0830", twin)[0]


def test_already_sent_verifies_exact_slot(monkeypatch):
    subjects = {b"1": b"Subject: Brief de Mercado - 11/05/2026 (8:30 AM)\r\n\r\n",
                b"2": b"Subject: Brief de Mercado - 11/05/2026 (10:30 AM)\r\n\r\n"}

    class FakeM:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def select(self, *a, **k): pass
        def search(self, *a): return "OK", [b"1 2"]
        def fetch(self, num, spec): return "OK", [(b"x", subjects[num])]
        def logout(self): pass

    import imaplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeM)
    monkeypatch.setenv("GMAIL_USER", "u@x.com"); monkeypatch.setenv("GMAIL_APP_PASSWORD", "p")
    assert rb._already_sent("Brief de Mercado - 11/05/2026 (8:30 AM)")
    assert rb._already_sent("Brief de Mercado - 11/05/2026 (10:30 AM)")
    assert not rb._already_sent("Brief de Mercado - 11/05/2026 (12:00 PM)")   # other slot NOT blocked
