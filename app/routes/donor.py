"""Puchar Dawcy PWr: słownik wydziałów, sprawdzenie tokenu rejestracyjnego (kodu OTP), przyznanie punktu wydziałowi."""
from __future__ import annotations

import hmac
import sqlite3
import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, config, db, qrtoken
from .game import attempts_left

router = APIRouter()
DUPLICATE_VOTE = "Z tego urządzenia oddano już głos w Pucharze."

# Globalny (nie per IP — eduroam) limit nietrafionych sprawdzeń kodu: utrudnia zgadywanie aktywnych kodów.
CHECK_MISSES_PER_MINUTE = 60
_misses: deque[float] = deque()
_misses_lock = threading.Lock()


def _check_throttled() -> bool:
    now = time.monotonic()
    with _misses_lock:
        while _misses and now - _misses[0] > 60:
            _misses.popleft()
        return len(_misses) >= CHECK_MISSES_PER_MINUTE


def _note_miss() -> None:
    with _misses_lock:
        _misses.append(time.monotonic())


class RegisterIn(BaseModel):
    code: str = Field(max_length=64)
    faculty: str = Field(max_length=32)
    device: str = Field(pattern=r"^[0-9a-f]{64}$")
    device_ext: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")


class RedeemPromoIn(BaseModel):
    code: str = Field(max_length=64)


def norm_code(code: str) -> str:
    return code.strip().upper()


def cup_device_hash(device: str, device_ext: str | None) -> str:
    """Skrót urządzenia do pilnowania jednego głosu (§3.5 regulaminu Pucharu): HMAC kluczem aplikacji ze stałą solą
    ``cup:``, bo sól dobowa nie pokryłaby całej akcji."""
    return hmac.new(config.secret_key().encode(), b"cup:" + (device_ext or device).encode(), "sha256").hexdigest()[:32]


@router.get("/api/dictionary/faculties")
def faculties(conn: sqlite3.Connection = Depends(db.get_db)):
    return {"faculties": db.get_dictionary(conn)["faculties"]}


@router.get("/api/donor/check-code")
def check_code(kod: str = "", conn: sqlite3.Connection = Depends(db.get_db)):
    if _check_throttled():
        raise HTTPException(429, "Za dużo prób sprawdzenia tokenu. Spróbuj za minutę.")
    db.expire_codes(conn)
    row = conn.execute("SELECT b.name, c.kind FROM (SELECT code, booth_id, status, kind FROM registration_codes "
                       "UNION ALL SELECT code, booth_id, status, 'promo' FROM promo_codes) c "
                       "JOIN booths b ON b.id=c.booth_id WHERE c.code=? AND c.status='ACTIVE'",
                       (norm_code(kod)[:64],)).fetchone()
    if row is None:
        _note_miss()
        return {"valid": False}
    bonus = {"actual": config.CUP_VOTE_BONUS_ACTUAL, "promo": config.PROMO_BONUS}.get(row["kind"], config.CUP_VOTE_BONUS)
    return {"valid": True, "booth_name": row["name"], "kind": row["kind"], "bonus": bonus}


def _grant_bonus(conn: sqlite3.Connection, sid: str | None, token: str | None, bonus: int) -> tuple[str, str | None]:
    """Dodatkowe próby w grze, w tej samej transakcji co zużycie kodu (kod jednorazowy = bonus raz na kod).
    Bez sesji gry tworzy nową (jak dawniej) i zwraca (session_id, token).
    Nowa sesja dostaje ``created_at`` z początku doby, nie z chwili głosu: w bazie nie ma więc nic, co wiązałoby
    głos (``donors_stats.created_at``) z sesją albo urządzeniem. Do ``donors_stats`` bonus nie trafia."""
    if sid is not None:
        conn.execute("UPDATE game_sessions SET bonus_attempts=bonus_attempts+? WHERE session_id=?", (bonus, sid))
    else:
        sid, token = auth.new_game_token()
        conn.execute("INSERT INTO game_sessions(session_id,created_at,bonus_attempts) VALUES(?,?,?)",
                     (sid, config.day_bounds(config.today())[0], bonus))
    return sid, token


@router.post("/api/donor/register")
def register(body: RegisterIn, request: Request, response: Response,
             sid: str | None = Depends(auth.optional_game_session),
             conn: sqlite3.Connection = Depends(db.get_db)):
    """Punkt dla wydziału za token rejestracyjny. Zapisujemy wyłącznie wydział, znacznik czasu i skrót urządzenia,
    a token unieważniamy (§3.4). Drugi głos z tego samego urządzenia = 409, a token zostaje ważny (§3.5).
    Dodatkowe próby w grze za udział w Pucharze dostaje tylko przyjęty głos (409/410/404/422 nie dają nic)."""
    if config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    code = norm_code(body.code)
    token = request.cookies.get(auth.GAME_COOKIE) or request.headers.get("X-Game-Token")
    device_hash = cup_device_hash(body.device, body.device_ext)
    with db.tx(conn):
        db.expire_codes(conn)
        row = conn.execute("SELECT c.*, b.name AS booth_name FROM registration_codes c "
                           "JOIN booths b ON b.id=c.booth_id WHERE c.code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "Nie znamy takiego tokenu. Sprawdź, czy został przepisany poprawnie.")
        if row["status"] != "ACTIVE":
            raise HTTPException(410, "Ten token został już użyty lub wygasł. Poproś wolontariusza o nowy.")
        fac = next((f for f in db.get_dictionary(conn)["faculties"] if f["code"] == body.faculty), None)
        if fac is None:
            raise HTTPException(422, "Nieznany wydział.")
        # Przed unieważnieniem tokenu: student może wpisać go z innego urządzenia.
        if conn.execute("SELECT 1 FROM donors_stats WHERE device_hash=?", (device_hash,)).fetchone():
            raise HTTPException(409, DUPLICATE_VOTE)
        conn.execute("UPDATE registration_codes SET status='USED', used_at=? WHERE code=?", (config.now_iso(), code))
        try:
            conn.execute("INSERT INTO donors_stats(faculty,created_at,device_hash) VALUES(?,?,?)",
                         (fac["code"], config.now_iso(), device_hash))
        except sqlite3.IntegrityError:
            raise HTTPException(409, DUPLICATE_VOTE)
        if row["kind"] == "actual":
            # Osobny licznik zbiorczy: typ dawcy nie może trafić do donors_stats (§3.4 Pucharu), a /puchar pokazuje
            # część faktycznych dawców w LD. Ta sama transakcja co głos; odrzucony głos (409) wyszedł wyżej.
            conn.execute("INSERT INTO cup_actual_counts(faculty,actual) VALUES(?,1) "
                         "ON CONFLICT(faculty) DO UPDATE SET actual=actual+1", (fac["code"],))
        bonus = config.CUP_VOTE_BONUS_ACTUAL if row["kind"] == "actual" else config.CUP_VOTE_BONUS
        sid, token = _grant_bonus(conn, sid, token, bonus)
    auth.set_game_cookie(response, token)
    return {"ok": True, "faculty": fac["code"], "faculty_name": fac["name"], "booth_name": row["booth_name"],
            "kind": row["kind"], "token": token, "bonus_attempts_granted": bonus,
            "attempts_left": attempts_left(conn, sid),
            "play_path": f"/graj?stoisko={row['booth_id']}&t={qrtoken.current(row['booth_id'])}"}


@router.post("/api/donor/redeem-promo")
def redeem_promo(body: RedeemPromoIn, request: Request, response: Response,
                 sid: str | None = Depends(auth.optional_game_session),
                 conn: sqlite3.Connection = Depends(db.get_db)):
    """Kod dodatkowych prób (+5 za post lub story): tylko dodatkowe próby, bez ``donors_stats`` i punktów Pucharu.
    Nie zależy od ``CUP_DEADLINE``."""
    code = norm_code(body.code)
    token = request.cookies.get(auth.GAME_COOKIE) or request.headers.get("X-Game-Token")
    with db.tx(conn):
        db.expire_codes(conn)
        row = conn.execute("SELECT c.*, b.name AS booth_name FROM promo_codes c "
                           "JOIN booths b ON b.id=c.booth_id WHERE c.code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "Nie znamy takiego kodu. Sprawdź, czy został przepisany poprawnie.")
        if row["status"] != "ACTIVE":
            raise HTTPException(410, "Ten kod został już użyty lub wygasł. Poproś wolontariusza o nowy.")
        conn.execute("UPDATE promo_codes SET status='USED', used_at=? WHERE code=?", (config.now_iso(), code))
        sid, token = _grant_bonus(conn, sid, token, config.PROMO_BONUS)
    auth.set_game_cookie(response, token)
    return {"ok": True, "booth_name": row["booth_name"], "token": token, "kind": "promo",
            "bonus_attempts_granted": config.PROMO_BONUS, "attempts_left": attempts_left(conn, sid),
            "play_path": f"/graj?stoisko={row['booth_id']}&t={qrtoken.current(row['booth_id'])}"}
