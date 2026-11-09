"""Kod QR stoiska zmieniający się co minutę.

Token = HMAC-SHA256(secret_key, "qr:<stoisko>:<minuta unixowa>"), skrócony do 10 znaków base32.
Ważny jest token z bieżącej i dwóch poprzednich minut (czas na zeskanowanie ok. 2-3 minut).
Czas wyłącznie przez ``config.now()``, żeby testy mogły go podmienić.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from . import config

LENGTH = 10
VALID_MINUTES = 3  # bieżąca + 2 poprzednie


def _minute() -> int:
    return int(config.now().timestamp() // 60)


def _token(booth_id: str, minute: int) -> str:
    mac = hmac.new(config.secret_key().encode(), f"qr:{booth_id}:{minute}".encode(), hashlib.sha256).digest()
    return base64.b32encode(mac).decode().rstrip("=").lower()[:LENGTH]


def current(booth_id: str) -> str:
    return _token(booth_id, _minute())


def valid(booth_id: str, token: str | None) -> bool:
    if not token or len(token) != LENGTH:
        return False
    minute = _minute()
    ok = False
    for m in range(minute, minute - VALID_MINUTES, -1):  # bez wcześniejszego wyjścia: stały czas
        ok |= hmac.compare_digest(_token(booth_id, m), token.strip().lower())
    return ok


def seconds_to_change() -> int:
    """Ile sekund zostało do zmiany bieżącego tokenu."""
    return 60 - int(config.now().timestamp() % 60)
