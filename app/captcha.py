"""Cloudflare Turnstile — ochrona sesji gry, rejestracji i logowania.

Klucze w ``.env``: ``TURNSTILE_SITE_KEY`` i ``TURNSTILE_SECRET_KEY``. Bez nich captcha jest
wyłączona (lokalnie, testy). Do Cloudflare NIE wysyłamy adresu IP (brak ``remoteip``),
a wyjątków dla sieci nie ma — eduroam nie jest blokowany.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

from fastapi import HTTPException, status

log = logging.getLogger("helpersi.captcha")

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def site_key() -> str:
    return os.environ.get("TURNSTILE_SITE_KEY", "").strip()


def _secret() -> str:
    return os.environ.get("TURNSTILE_SECRET_KEY", "").strip()


def enabled() -> bool:
    if os.environ.get("TURNSTILE_EXEMPT", "").strip() == "1":
        return False
    return bool(site_key() and _secret())


def _siteverify(token: str) -> bool:
    body = urllib.parse.urlencode({"secret": _secret(), "response": token}).encode()
    req = urllib.request.Request(VERIFY_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — stały adres Cloudflare
            result = json.load(resp)
    except Exception as exc:
        log.warning("Turnstile siteverify nie odpowiada: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Nie udało się sprawdzić captchy. Spróbuj ponownie za chwilę.") from exc
    if not result.get("success"):
        log.info("Turnstile odrzucił token: %s", result.get("error-codes"))
    return bool(result.get("success"))


def require(token: str | None) -> None:
    """Rzuć 400, gdy captcha jest włączona, a token jest pusty albo nieważny."""
    if not enabled():
        return
    if not token or len(token) > 2048 or not _siteverify(token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Potwierdź, że nie jesteś robotem (captcha).")
