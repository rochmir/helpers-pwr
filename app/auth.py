"""Sesje: gracz (podpisany token w ciasteczku) i personel (konto z rolą admin / wolontariusz).

Żadnych adresów IP — throttle logowania jest per login, w pamięci procesu.
"""
from __future__ import annotations

import hmac
import secrets
import sqlite3
import threading
import time

from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, Signer, URLSafeTimedSerializer

from . import config
from .db import get_db, hasher

GAME_COOKIE = "hp_game"
STAFF_COOKIE = "hp_staff"
GAME_MAX_AGE = 30 * 24 * 3600
ADMIN_MAX_AGE = 12 * 3600
VOLUNTEER_MAX_AGE = 14 * 3600
ADMIN_LOGIN = "admin"      # awaryjne konto: hasło = ADMIN_SECRET, bez wiersza w bazie; login zastrzeżony


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


def optional_game_session(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> str | None:
    """Id istniejącej sesji gry z ciasteczka ``hp_game``; None, gdy brak/nieważna."""
    sid = read_game_token(request.cookies.get(GAME_COOKIE))
    if sid is None:
        return None
    if conn.execute("SELECT 1 FROM game_sessions WHERE session_id=?", (sid,)).fetchone() is None:
        return None
    return sid


def ensure_game_session(conn: sqlite3.Connection, request: Request, response: Response) -> str:
    """Istniejąca sesja gry albo nowa (``created_at`` = początek doby, żeby nic nie wiązało sesji z chwilą głosu);
    nowej ustawia ciasteczko."""
    sid = optional_game_session(request, conn)
    if sid is not None:
        return sid
    sid, token = new_game_token()
    conn.execute("INSERT INTO game_sessions(session_id,created_at) VALUES(?,?)",
                 (sid, config.day_bounds(config.today())[0]))
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


def set_staff_cookie(response: Response, role: str, payload: dict) -> None:
    """Cookie ``{login, ph, booth}``; rola nie jest w cookie (czytamy ją z bazy przy każdym żądaniu)."""
    max_age = ADMIN_MAX_AGE if role == "admin" else VOLUNTEER_MAX_AGE
    response.set_cookie(STAFF_COOKIE, _staff_serializer().dumps(payload), max_age=max_age, httponly=True,
                        samesite="strict", secure=config.cookie_secure(), path="/")


def clear_staff_cookie(response: Response) -> None:
    response.delete_cookie(STAFF_COOKIE, path="/")


def hash_tag(password_hash: str) -> str:
    """Końcówka hasha hasła w cookie: reset hasła unieważnia stare sesje."""
    return password_hash[-8:]


def _admin_tag() -> str:
    """Odpowiednik ``hash_tag`` dla konta awaryjnego: zmiana ``ADMIN_SECRET`` unieważnia jego sesje."""
    return hmac.new(config.secret_key().encode(), b"admin:" + config.admin_secret().encode(), "sha256").hexdigest()[:8]


def verify_login(conn: sqlite3.Connection, login: str, password: str) -> dict | None:
    """Sprawdza login i hasło (konto z bazy albo awaryjne ``admin`` + ``ADMIN_SECRET``).
    Zwraca ``{login, role, ph}`` albo None."""
    if login == ADMIN_LOGIN:
        return {"login": login, "role": "admin", "ph": _admin_tag()} if check_admin_secret(password) else None
    row = conn.execute("SELECT password_hash, role FROM volunteers WHERE login=?", (login,)).fetchone()
    if row is None:
        return None
    try:
        hasher.verify(row["password_hash"], password)
    except (VerifyMismatchError, InvalidHashError):
        return None
    return {"login": login, "role": row["role"], "ph": hash_tag(row["password_hash"])}


def current_staff(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Zweryfikowany personel: ``{role, login, booth, ph}`` (``booth`` None, gdy nie wybrano). 401 gdy brak.
    Rola pochodzi z bazy, więc degradacja i reset hasła działają od razu."""
    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Zaloguj się.")
    token = request.cookies.get(STAFF_COOKIE)
    if not token:
        raise unauth
    try:
        data, ts = _staff_serializer().loads(token, max_age=VOLUNTEER_MAX_AGE, return_timestamp=True)
    except BadSignature:
        raise unauth
    login = data.get("login") if isinstance(data, dict) else None
    if not login:
        raise unauth
    if login == ADMIN_LOGIN:
        if not config.admin_secret() or not hmac.compare_digest(_admin_tag(), str(data.get("ph", ""))):
            raise unauth
        role = "admin"
    else:
        row = conn.execute("SELECT password_hash, role FROM volunteers WHERE login=?", (login,)).fetchone()
        if row is None or not hmac.compare_digest(hash_tag(row["password_hash"]), str(data.get("ph", ""))):
            raise unauth  # konto usunięte albo hasło zmienione
        role = row["role"]
    if role == "admin" and (config.now() - ts).total_seconds() > ADMIN_MAX_AGE:
        raise unauth
    booth = data.get("booth")
    if booth and conn.execute("SELECT 1 FROM booths WHERE id=?", (booth,)).fetchone() is None:
        booth = None
    return {"role": role, "login": login, "booth": booth or None, "ph": str(data.get("ph", ""))}


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
    """Stoisko, na którym wolno działać: wolontariusz tylko wybrane, admin podaje ``booth_id`` albo używa wybranego."""
    if staff["role"] == "volunteer":
        if not staff["booth"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Wybierz stoisko.")
        if booth_id and booth_id != staff["booth"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "To nie jest Twoje stoisko.")
        return staff["booth"]
    bid = booth_id or staff["booth"]
    if not bid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Podaj booth_id.")
    return bid
