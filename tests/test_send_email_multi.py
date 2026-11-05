"""BRIEF_EMAIL_TO accepts several comma-separated recipients (offline: SMTP/Resend mocked)."""
import importlib.util
import json
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "send_email", Path(__file__).resolve().parents[1] / "scripts" / "daily_brief" / "send_email.py")
se = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(se)


def test_recipients_parsing():
    assert se._recipients("a@x.com") == ["a@x.com"]
    assert se._recipients(" a@x.com , b@y.com;A@X.com,") == ["a@x.com", "b@y.com"]
    assert se._recipients(None) == []


def test_smtp_sends_to_all(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): sent["user"] = u
        def send_message(self, msg): sent["to"] = msg["To"]; sent["subject"] = msg["Subject"]

    monkeypatch.setattr(se.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("GMAIL_USER", "me@x.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("BRIEF_EMAIL_TO", "me@x.com,she@y.com")
    se.send_email("Cierre de Mercado - 01/01/2026", "<b>hi</b>", html=True)
    assert sent["to"] == "me@x.com, she@y.com"
    assert sent["user"] == "me@x.com"
    assert sent["subject"] == "Cierre de Mercado - 01/01/2026"


def test_resend_sends_list(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data)
        return FakeResp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RENDER", "1")
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("BRIEF_EMAIL_TO", "me@x.com,she@y.com")
    se.send_email("s", "body", html=False)
    assert captured["body"]["to"] == ["me@x.com", "she@y.com"]
