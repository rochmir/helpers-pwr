"""Kod QR stoiska zmieniający się co minutę.

Token = HMAC-SHA256(secret_key, "qr:<stoisko>:<minuta unixowa>"), skrócony do 10 znaków base32.
Ważny jest token z bieżącej i dwóch poprzednich minut (czas na zeskanowanie ok. 2-3 minut).
Czas wyłącznie przez ``config.now()``, żeby testy mogły go podmienić.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re

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


# --- kod QR do głosu w Pucharze / postu (bezstanowy, wielokrotnego użytku w oknie 60 s) ----------------
class CupTokenError(Exception):
    """Token Pucharu nieprawidłowy (zła forma, podpis, kategoria albo czas z przyszłości)."""


class CupTokenExpired(CupTokenError):
    """Token Pucharu prawidłowy, ale starszy niż okno ważności."""


CAT_CODE = {"nowy": "n", "zarejestrowany": "z", "faktyczny": "f", "post": "p"}
_CODE_CAT = {v: k for k, v in CAT_CODE.items()}
_BOOTH_RE = re.compile(r"[a-z0-9]{1,20}")
_IAT_RE = re.compile(r"[0-9a-f]{1,12}")


def _cup_mac(payload: str) -> str:
    mac = hmac.new(config.secret_key().encode(), b"cup1:" + payload.encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def cup_issue(booth_id: str, category: str) -> tuple[str, int]:
    """Token ``stoisko.kat.iat.mac``; zwraca (token, iat w sekundach unixowych). Nie zapisujemy go nigdzie."""
    iat = int(config.now().timestamp())
    payload = f"{booth_id}.{CAT_CODE[category]}.{iat:x}"
    return f"{payload}.{_cup_mac(payload)}", iat


def cup_verify(token: str) -> tuple[str, str]:
    """(stoisko, kategoria) z poprawnego tokenu; CupTokenError / CupTokenExpired w innym razie."""
    if not isinstance(token, str) or len(token) > 100:
        raise CupTokenError("długość")
    parts = token.split(".")
    if len(parts) != 4:
        raise CupTokenError("format")
    booth, code, iat_hex, mac = parts
    if not _BOOTH_RE.fullmatch(booth) or code not in _CODE_CAT or not _IAT_RE.fullmatch(iat_hex):
        raise CupTokenError("pola")
    if not hmac.compare_digest(_cup_mac(f"{booth}.{code}.{iat_hex}"), mac):
        raise CupTokenError("podpis")
    age = int(config.now().timestamp()) - int(iat_hex, 16)  # pełne sekundy, jak w iat
    if age < -config.CUP_QR_LEEWAY_SECONDS:
        raise CupTokenError("z przyszłości")
    if age > config.CUP_QR_TTL_SECONDS + config.CUP_QR_LEEWAY_SECONDS:
        raise CupTokenExpired("wygasł")
    return booth, _CODE_CAT[code]
