"""Legitymacje dawców faktycznych: w bazie trzymamy tylko klucz HMAC, nigdy jawny numer ani datę."""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date

from . import config

MAX_LEN = 40


def normalize_number(raw: str) -> str:
    """Trim, bez spacji i myślników, wielkie litery. Pusty wynik lub >40 znaków = ValueError."""
    n = re.sub(r"[\s-]+", "", raw or "").upper()
    if not n or len(n) > MAX_LEN:
        raise ValueError("number")
    return n


def card_hash(number: str, issued: str) -> str:
    """HMAC-SHA256(secret_key, "card:<numer>|<data ISO>") w hex. Rzuca ValueError przy złych danych."""
    n = normalize_number(number)
    iso = date.fromisoformat(issued).isoformat()
    return hmac.new(config.secret_key().encode(), f"card:{n}|{iso}".encode(), hashlib.sha256).hexdigest()
