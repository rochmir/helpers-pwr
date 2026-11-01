"""Puchar Dawcy PWr: słownik wydziałów, sprawdzenie tokenu rejestracyjnego (kodu OTP), przyznanie punktu wydziałowi."""
from __future__ import annotations

import hmac
import sqlite3
import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import captcha, config, db

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
    cf_turnstile: str | None = Field(None, max_length=4096)


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
    row = conn.execute("SELECT b.name, c.kind FROM registration_codes c JOIN booths b ON b.id=c.booth_id "
                       "WHERE c.code=? AND c.status='ACTIVE'", (norm_code(kod)[:64],)).fetchone()
    if row is None:
        _note_miss()
        return {"valid": False}
    return {"valid": True, "booth_name": row["name"], "kind": row["kind"]}


@router.post("/api/donor/register")
def register(body: RegisterIn, conn: sqlite3.Connection = Depends(db.get_db)):
    """Punkt dla wydziału za token rejestracyjny. Zapisujemy wyłącznie wydział, znacznik czasu i skrót urządzenia,
    a token unieważniamy (§3.4). Drugi głos z tego samego urządzenia = 409, a token zostaje ważny (§3.5)."""
    if config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    captcha.require(body.cf_turnstile)
    code = norm_code(body.code)
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
    return {"ok": True, "faculty": fac["code"], "faculty_name": fac["name"], "booth_name": row["booth_name"],
            "kind": row["kind"]}
