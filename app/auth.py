"""Sesje: gracz (podpisany token, cookie lub nagłówek) i personel (admin / wolontariusz).

Żadnych adresów IP — throttle logowania jest per login, w pamięci procesu.
"""
from __future__ import annotations

import hmac
import secrets
import sqlite3
import threading
import time

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, Signer, URLSafeTimedSerializer

from . import config
from .db import get_db

GAME_COOKIE = "hp_game"
STAFF_COOKIE = "hp_staff"
GAME_MAX_AGE = 30 * 24 * 3600
ADMIN_MAX_AGE = 12 * 3600
VOLUNTEER_MAX_AGE = 14 * 3600


# --- sesja gry ------------------------------------------------------------------
def _game_signer() -> Signer:
    return Signer(config.secret_key(), salt="game")


def new_game_token() -> tuple[str, str]:
    sid = secrets.token_urlsafe(24)
    return sid, _game_signer().sign(sid).decode()


def read_game_token(token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    try:
        return _game_signer().unsign(token).decode()
    except BadSignature:
        return None


def set_game_cookie(response: Response, token: str) -> None:
    response.set_cookie(GAME_COOKIE, token, max_age=GAME_MAX_AGE, httponly=True,
                        samesite="lax", secure=config.cookie_secure(), path="/")


def optional_game_session(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> str | None:
    """Id istniejącej sesji gry (cookie lub ``X-Game-Token``); None, gdy brak/nieważna."""
    from_cookie = request.cookies.get(GAME_COOKIE)
    token = from_cookie or request.headers.get("X-Game-Token")
    sid = read_game_token(token)
    if sid is None:
        return None
    if conn.execute("SELECT 1 FROM game_sessions WHERE session_id=?", (sid,)).fetchone() is None:
        return None
    if not from_cookie:  # tylko nagłówek — odnów cookie
        set_game_cookie(response, token)
    return sid


def game_session(sid: str | None = Depends(optional_game_session)) -> str:
    if sid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Brak sesji gry. Odśwież stronę.")
    return sid


# --- throttle logowania (per login) ---------------------------------------------
class Throttle:
    """10 błędów w 10 minut -> blokada logowania na 5 minut."""
    MAX_FAILS = 10
    WINDOW = 600
    LOCK = 300

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            until = self._locked.get(key, 0)
            if until > time.monotonic():
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    "Zbyt wiele błędnych prób. Spróbuj ponownie za kilka minut.")

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._fails) > 1000:
                self._fails.clear()
            fails = [t for t in self._fails.get(key, []) if now - t < self.WINDOW] + [now]
            self._fails[key] = fails
            if len(fails) >= self.MAX_FAILS:
                self._locked[key] = now + self.LOCK
                self._fails.pop(key, None)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._fails.clear()
                self._locked.clear()
            else:
                self._fails.pop(key, None)
                self._locked.pop(key, None)


throttle = Throttle()


def check_admin_secret(candidate: str) -> bool:
    expected = config.admin_secret()
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


# --- personel -------------------------------------------------------------------
def _staff_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.secret_key(), salt="staff")


def set_staff_cookie(response: Response, payload: dict) -> None:
    max_age = ADMIN_MAX_AGE if payload["role"] == "admin" else VOLUNTEER_MAX_AGE
    response.set_cookie(STAFF_COOKIE, _staff_serializer().dumps(payload), max_age=max_age, httponly=True,
                        samesite="strict", secure=config.cookie_secure(), path="/")


def clear_staff_cookie(response: Response) -> None:
    response.delete_cookie(STAFF_COOKIE, path="/")


def hash_tag(password_hash: str) -> str:
    """Końcówka hasha hasła w cookie: reset hasła unieważnia stare sesje wolontariusza."""
    return password_hash[-8:]


def current_staff(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Zweryfikowany personel: ``{role:'admin'}`` albo ``{role:'volunteer', booth:id, login}``. 401 gdy brak."""
    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Zaloguj się.")
    token = request.cookies.get(STAFF_COOKIE)
    if not token:
        raise unauth
    try:
        data, ts = _staff_serializer().loads(token, max_age=VOLUNTEER_MAX_AGE, return_timestamp=True)
    except BadSignature:
        raise unauth
    role = data.get("role")
    if role == "admin":
        if (config.now() - ts).total_seconds() > ADMIN_MAX_AGE:
            raise unauth
        return {"role": "admin"}
    if role == "volunteer":
        login = data.get("login")
        row = conn.execute("SELECT password_hash FROM volunteers WHERE login=?", (login,)).fetchone() if login else None
        if row is None or not hmac.compare_digest(hash_tag(row["password_hash"]), str(data.get("ph", ""))):
            raise unauth  # konto usunięte albo hasło zmienione
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (data.get("booth"),)).fetchone() is None:
            raise unauth
        return {"role": "volunteer", "booth": data["booth"], "login": login}
    raise unauth


def optional_staff(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict | None:
    """Jak ``current_staff``, ale None zamiast 401."""
    try:
        return current_staff(request, conn)
    except HTTPException:
        return None


def require_admin(staff: dict = Depends(current_staff)) -> dict:
    if staff["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnień administratora.")
    return staff


def require_volunteer(staff: dict = Depends(current_staff)) -> dict:
    """Wolontariusz lub admin (nadzbiór)."""
    return staff


def resolve_booth(staff: dict, booth_id: str | None) -> str:
    """Stoisko, na którym wolno działać: wolontariusz tylko swoje, admin podaje ``booth_id``."""
    if staff["role"] == "volunteer":
        if booth_id and booth_id != staff["booth"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "To nie jest Twoje stoisko.")
        return staff["booth"]
    if not booth_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Podaj booth_id.")
    return booth_id
