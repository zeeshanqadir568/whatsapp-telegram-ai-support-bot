"""Tests for the public-deployment guards in security.py and their wiring in app.py."""

import hashlib
import hmac
import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import app
from security import RateLimiter, chat_limiter, client_ip


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_limiter():
    """Every test starts with an empty rate-limit window."""
    chat_limiter._hits.clear()
    chat_limiter._day_count = 0
    yield


# --- admin-only endpoints -------------------------------------------------

def test_leads_disabled_without_admin_token(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.get("/api/leads").status_code == 403


def test_leads_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "right-token")
    assert client.get("/api/leads", headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_leads_allowed_with_admin_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "right-token")
    response = client.get("/api/leads", headers={"X-Admin-Token": "right-token"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_upload_disabled_without_admin_token(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    files = {"file": ("faq.txt", b"hello", "text/plain")}
    assert client.post("/api/upload", files=files).status_code == 403


def test_upload_strips_path_traversal(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    files = {"file": ("../../evil.txt", b"Refunds are accepted within 30 days.", "text/plain")}
    response = client.post("/api/upload", files=files, headers={"X-Admin-Token": "t"})
    try:
        assert response.status_code == 200
        assert response.json()["filename"] == "evil.txt"
        assert not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "..", "evil.txt"))
    finally:
        saved = os.path.join(os.path.dirname(__file__), "..", "uploads", "evil.txt")
        if os.path.exists(saved):
            os.remove(saved)


def test_upload_rejects_files_over_5mb(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    files = {"file": ("big.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")}
    response = client.post("/api/upload", files=files, headers={"X-Admin-Token": "t"})
    assert response.status_code == 413


# --- chat abuse limits ----------------------------------------------------

def test_chat_rejects_overlong_message(client):
    payload = {"message": "a" * 1001, "session_id": "s", "channel": "api"}
    assert client.post("/chat", json=payload).status_code == 422


def test_chat_is_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(chat_limiter, "per_minute", 2)
    payload = {"message": "What are your hours?", "session_id": "rl", "channel": "api"}
    codes = [client.post("/chat", json=payload).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_rate_limiter_daily_cap_applies_across_ips():
    limiter = RateLimiter(per_minute=100, per_day=2)
    limiter.check("1.1.1.1")
    limiter.check("2.2.2.2")
    with pytest.raises(HTTPException) as exc:
        limiter.check("3.3.3.3")
    assert exc.value.status_code == 429


def test_rate_limiter_keys_are_independent():
    limiter = RateLimiter(per_minute=1, per_day=100)
    limiter.check("a")
    limiter.check("b")  # different IP, own window
    with pytest.raises(HTTPException):
        limiter.check("a")


class _FakeRequest:
    def __init__(self, forwarded, host="10.0.0.1"):
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_ignores_spoofed_left_entries(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert client_ip(_FakeRequest("6.6.6.6, 203.0.113.7")) == "203.0.113.7"


def test_client_ip_falls_back_to_socket(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert client_ip(_FakeRequest("6.6.6.6")) == "10.0.0.1"


# --- webhooks -------------------------------------------------------------

def test_telegram_webhook_requires_secret(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "tg-secret")
    update = {"message": {"chat": {"id": 1}, "text": ""}}
    assert client.post("/webhook/telegram", json=update).status_code == 403
    ok = client.post(
        "/webhook/telegram", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "ignored"


def test_whatsapp_webhook_checks_meta_signature(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": []}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json"}

    bad = client.post("/webhook/whatsapp", content=body, headers={**headers, "X-Hub-Signature-256": "sha256=0"})
    assert bad.status_code == 403

    good = client.post("/webhook/whatsapp", content=body, headers={**headers, "X-Hub-Signature-256": sig})
    assert good.status_code == 200 and good.json()["status"] == "ignored"


def test_whatsapp_verification_uses_meta_query_names(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    params = {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "12345"}
    response = client.get("/webhook/whatsapp", params=params)
    assert response.status_code == 200 and response.json() == 12345

    params["hub.verify_token"] = "wrong"
    assert client.get("/webhook/whatsapp", params=params).status_code == 403
