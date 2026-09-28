"""Guards for running the bot on a public URL.

- Admin endpoints (leads, uploads) need an ``X-Admin-Token`` header matching
  ``ADMIN_TOKEN``. With no ``ADMIN_TOKEN`` set they are disabled (fail closed),
  so a public demo never exposes visitors' contact details.
- ``/chat`` is rate limited per client IP and by a global daily cap, so a
  public demo cannot run up the LLM bill.
- Webhooks only accept requests that prove they come from Telegram / Meta.
"""

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, status


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """FastAPI dependency: allow the request only with the correct admin token."""
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is disabled on this deployment.")
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin token.")


def client_ip(request: Request) -> str:
    """Client IP for rate limiting.

    Behind a reverse proxy (HF Spaces, Render, ...) the real IP is appended to
    X-Forwarded-For by the proxy, so read it from the right: the left-most
    entries are client-controlled and trivially spoofed. TRUSTED_PROXY_HOPS is
    how many proxies sit in front of the app (0 = use the socket address).
    """
    hops = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))
    forwarded = [ip.strip() for ip in request.headers.get("x-forwarded-for", "").split(",") if ip.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """In-memory sliding-window limiter: N requests per key per minute, plus a global daily cap.

    In-memory is enough for a single-process deployment; use Redis if you scale out.
    """

    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self._hits: dict[str, deque] = defaultdict(deque)
        self._day = time.strftime("%Y-%m-%d", time.gmtime())
        self._day_count = 0
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if today != self._day:
                self._day, self._day_count = today, 0
            if self._day_count >= self.per_day:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "The demo has reached its daily message limit. Please try again tomorrow.",
                )

            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many messages. Please wait a minute and try again.",
                )
            hits.append(now)
            self._day_count += 1


chat_limiter = RateLimiter(
    per_minute=int(os.getenv("CHAT_RATE_PER_MINUTE", "10")),
    per_day=int(os.getenv("CHAT_DAILY_CAP", "500")),
)


def verify_telegram(x_telegram_bot_api_secret_token: str = Header(default="")) -> None:
    """Telegram sends the secret given to setWebhook(secret_token=...) in this header."""
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected or not hmac.compare_digest(x_telegram_bot_api_secret_token.encode(), expected.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook secret.")


async def verify_whatsapp(request: Request, x_hub_signature_256: str = Header(default="")) -> None:
    """Meta signs each webhook body with the app secret (HMAC-SHA256)."""
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "WhatsApp webhook is not configured.")
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(x_hub_signature_256.encode(), expected.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook signature.")
