"""Dawca: słownik wydziałów, sprawdzenie kodu, wpisanie kodu ze stoiska (bez zapisu kodu i godziny w statystykach)."""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, captcha, config, db, qrtoken
from .game import attempts_left

router = APIRouter()

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
    study_year: int
    cf_turnstile: str | None = Field(None, max_length=4096)


def norm_code(code: str) -> str:
    return code.strip().upper()


@router.get("/api/dictionary/faculties")
def faculties(conn: sqlite3.Connection = Depends(db.get_db)):
    d = db.get_dictionary(conn)
    return {"faculties": d["faculties"], "study_years": db.study_years()}


@router.get("/api/donor/check-code")
def check_code(kod: str = "", conn: sqlite3.Connection = Depends(db.get_db)):
    if _check_throttled():
        raise HTTPException(429, "Za dużo prób sprawdzenia kodu. Spróbuj za minutę.")
    db.expire_codes(conn)
    row = conn.execute("SELECT b.name, c.kind FROM registration_codes c JOIN booths b ON b.id=c.booth_id "
                       "WHERE c.code=? AND c.status='ACTIVE'", (norm_code(kod)[:64],)).fetchone()
    if row is None:
        _note_miss()
        return {"valid": False}
    return {"valid": True, "booth_name": row["name"], "kind": row["kind"]}


@router.post("/api/donor/register")
def register(body: RegisterIn, request: Request, response: Response,
             sid: str | None = Depends(auth.optional_game_session),
             conn: sqlite3.Connection = Depends(db.get_db)):
    captcha.require(body.cf_turnstile)
    code = norm_code(body.code)
    token = request.cookies.get(auth.GAME_COOKIE) or request.headers.get("X-Game-Token")
    with db.tx(conn):
        db.expire_codes(conn)
        row = conn.execute("SELECT c.*, b.name AS booth_name FROM registration_codes c "
                           "JOIN booths b ON b.id=c.booth_id WHERE c.code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "Nie znamy takiego kodu. Sprawdź, czy został przepisany poprawnie.")
        if row["status"] != "ACTIVE":
            raise HTTPException(410, "Ten kod został już użyty lub wygasł. Poproś wolontariusza o nowy.")
        fac = next((f for f in db.get_dictionary(conn)["faculties"] if f["code"] == body.faculty), None)
        if fac is None:
            raise HTTPException(422, "Nieznany wydział.")
        if body.study_year not in {y["value"] for y in db.study_years()}:
            raise HTTPException(422, "Niepoprawny rok studiów.")
        conn.execute("UPDATE registration_codes SET status='USED', used_at=? WHERE code=?", (config.now_iso(), code))
        conn.execute("INSERT INTO donors_stats(booth_id,faculty,study_year,registered_date,kind) VALUES(?,?,?,?,?)",
                     (row["booth_id"], fac["code"], body.study_year, config.today(), row["kind"]))
        bonus = config.REGISTER_BONUS
        if row["kind"] == "actual":
            bonus = config.REGISTER_BONUS_ACTUAL
            try:  # klucz legitymacji jest unikalny: druga rejestracja tej samej karty = 409
                conn.execute("INSERT INTO actual_donor_cards(card_hash,registered_date) VALUES(?,?)",
                             (row["card_hash"], config.today()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Ta legitymacja jest już zarejestrowana w systemie.")
        # +10 prób w grze, w tej samej transakcji co zużycie kodu (kod jednorazowy = bonus raz na kod).
        if sid is not None:
            conn.execute("UPDATE game_sessions SET bonus_attempts=bonus_attempts+? WHERE session_id=?",
                         (bonus, sid))
        else:
            sid, token = auth.new_game_token()
            conn.execute("INSERT INTO game_sessions(session_id,created_at,bonus_attempts) VALUES(?,?,?)",
                         (sid, config.now_iso(), bonus))
    auth.set_game_cookie(response, token)
    return {"ok": True, "faculty": fac["code"], "faculty_name": fac["name"], "booth_name": row["booth_name"],
            "token": token, "kind": row["kind"], "bonus_attempts_granted": bonus,
            "attempts_left": attempts_left(conn, sid),
            "play_path": f"/graj?stoisko={row['booth_id']}&t={qrtoken.current(row['booth_id'])}"}
