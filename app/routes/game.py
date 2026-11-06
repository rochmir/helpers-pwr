"""Symulator HLA: stan stoiska, sesja gracza, przepustka ze skanu QR, sprawdzanie parametrów (rzut genotypu)."""
from __future__ import annotations

import hmac
import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import auth, config, db, game, qrtoken, testing

router = APIRouter()
SCAN_AGAIN = "Zeskanuj ponownie kod QR ze stoiska."
BOOTH_LIMIT = "Limit prób na tym stanowisku na dziś wykorzystany. Zagraj na innym stanowisku albo wróć jutro."
WON_FIELDS = ("won_token", "won_seq", "won_booth_name", "won_genotype", "won_at")
CONSENT_REQUIRED = "Zaakceptuj regulamin i politykę prywatności."


class _LimitReached(Exception):
    pass


class SessionIn(BaseModel):
    """Puste ciało; nadmiarowe pola (np. dawne ``cf_turnstile`` ze starszego frontendu) są ignorowane."""


class RollIn(BaseModel):
    booth_id: str = Field(max_length=40)


class EnterIn(BaseModel):
    booth_id: str = Field(max_length=40)
    t: str = Field(max_length=64)
    device: str = Field(pattern=r"^[0-9a-f]{64}$")
    device_ext: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    consent: bool = False


def booth_pool(conn: sqlite3.Connection, device_key: str, ext_key: str | None, booth_id: str, sid: str, date: str) -> int:
    """Próby, które zostały sesji na stanowisku dziś (§4.2 regulaminu: 5 na dobę na urządzenie na każdym stanowisku).
    Limit 5 trzyma klucz rozszerzony (``ext_key``: wszystkie sesje tego samego egzemplarza dzielą 5 prób), a klucz
    podstawowy daje sufit 5 * tolerancja dla identycznych urządzeń."""
    ext_key = ext_key or device_key
    rows = conn.execute("SELECT session_id, ext_key, attempts FROM booth_plays WHERE device_key=? AND booth_id=? AND date=?",
                        (device_key, booth_id, date)).fetchall()
    mine = sum(r["attempts"] for r in rows if r["session_id"] == sid)
    total = sum(r["attempts"] for r in rows)
    ext_total = sum(r["attempts"] for r in rows if r["ext_key"] == ext_key)
    return max(0, min(config.DAILY_ATTEMPTS - max(mine, ext_total),
                      config.DAILY_ATTEMPTS * db.device_tolerance(conn) - total))


def game_state(conn: sqlite3.Connection, sid: str) -> dict:
    """Stan gracza: próby (pula stanowiska przepustki + dodatkowe), najlepszy wynik dnia, ważna przepustka, ostatnie trafienie."""
    s = conn.execute("SELECT has_won, bonus_attempts, pass_booth, pass_until, device_key, device_ext_key, won_genotype, won_at, won_token "
                     "FROM game_sessions WHERE session_id=?", (sid,)).fetchone()
    a = conn.execute("SELECT best FROM game_attempts WHERE session_id=? AND date=?", (sid, config.today())).fetchone()
    pass_ok = bool(s["pass_booth"] and s["pass_until"] and s["pass_until"] > config.now_iso())
    left = config.DAILY_ATTEMPTS
    if pass_ok and s["device_key"]:
        left = booth_pool(conn, s["device_key"], s["device_ext_key"], s["pass_booth"], sid, config.today())
    lecture = bool(pass_ok and conn.execute("SELECT is_lecture FROM booths WHERE id=?", (s["pass_booth"],)).fetchone()[0])
    win = conn.execute("SELECT w.seq, b.name FROM wins w LEFT JOIN booths b ON b.id=w.booth_id WHERE w.token=?",
                       (s["won_token"],)).fetchone() if s["won_token"] else None
    return {"attempts_left": left + s["bonus_attempts"], "booth_left": left,
            "bonus_attempts": s["bonus_attempts"], "has_won": bool(s["has_won"]),
            "best_today": a["best"] if a else 0, "pass_booth": s["pass_booth"] if pass_ok else None, "pass_is_lecture": lecture,
            "won_genotype": s["won_genotype"], "won_at": s["won_at"], "won_token": s["won_token"],
            "won_seq": win["seq"] if win else None, "won_booth_name": win["name"] if win else None}


def attempts_left(conn: sqlite3.Connection, sid: str) -> int:
    return game_state(conn, sid)["attempts_left"]


@router.get("/api/booth/{booth_id}/state")
def booth_state(booth_id: str, screen: str | None = None, staff: dict | None = Depends(auth.optional_staff),
                conn: sqlite3.Connection = Depends(db.get_db)):
    b = conn.execute("SELECT * FROM booths WHERE id=?", (booth_id,)).fetchone()
    if b is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    out = {"id": b["id"], "name": b["name"], "genotype": b["current_genotype"],
           "genotype_updated_at": b["genotype_updated_at"], "matches_count": b["matches_count"],
           "rolls_count": b["rolls_count"], "play_path": None, "qr_seconds_left": None}
    # Ważny link do gry (aktualny token QR) dostaje tylko personel tego stoiska; publicznie go nie ma.
    # Ekran Zajęć (statyczny link /zajecia/{token}) dostaje QR bez logowania, ale tylko dla stanowiska is_lecture.
    if (staff and (staff["role"] == "admin" or staff.get("booth") == b["id"])) or \
            (b["is_lecture"] and db.lecture_token_ok(conn, screen)):
        out["play_path"] = f"/graj?stoisko={b['id']}&t={qrtoken.current(b['id'])}"
        out["qr_seconds_left"] = qrtoken.seconds_to_change()
    return out


@router.post("/api/game/session")
def create_session(body: SessionIn, request: Request, response: Response,
                   sid: str | None = Depends(auth.optional_game_session),
                   conn: sqlite3.Connection = Depends(db.get_db)):
    if sid is not None:  # ważna sesja zostaje
        token = request.cookies.get(auth.GAME_COOKIE) or request.headers.get("X-Game-Token")
        auth.set_game_cookie(response, token)
    else:
        sid, token = auth.new_game_token()
        conn.execute("INSERT INTO game_sessions(session_id,created_at) VALUES(?,?)", (sid, config.now_iso()))
        auth.set_game_cookie(response, token)
    return {"token": token, **game_state(conn, sid)}


@router.get("/api/game/me")
def me(sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    return game_state(conn, sid)


@router.post("/api/game/enter")
def enter(body: EnterIn, sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    """Przepustka na stoisko po zeskanowaniu aktualnego kodu QR; kolejne skanowanie ją odnawia.
    Zapisuje zgodę i pseudonimowy klucz urządzenia: HMAC hasha z przeglądarki solą dobową (surowego hasha nie trzymamy)."""
    if not body.consent:
        raise HTTPException(422, CONSENT_REQUIRED)
    if conn.execute("SELECT 1 FROM booths WHERE id=?", (body.booth_id,)).fetchone() is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    if not qrtoken.valid(body.booth_id, body.t):
        raise HTTPException(403, "Ten kod QR wygasł. " + SCAN_AGAIN)
    until = config.iso(config.now() + timedelta(minutes=config.PASS_MINUTES))
    salt = db.device_salt(conn).encode()
    key = hmac.new(salt, body.device.encode(), "sha256").hexdigest()[:32]
    # klucz rozszerzony: ta sama sol, inny prefiks; brak device_ext = klucz podstawowy
    ext_key = hmac.new(salt, b"ext:" + (body.device_ext or body.device).encode(), "sha256").hexdigest()[:32]
    conn.execute("UPDATE game_sessions SET pass_booth=?, pass_until=?, device_key=?, device_ext_key=?, consent_at=? "
                 "WHERE session_id=?", (body.booth_id, until, key, ext_key, config.now_iso(), sid))
    return {"ok": True, "pass_until": until}


@router.post("/api/game/roll")
def roll(body: RollIn, sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    db.device_salt(conn)  # nowy dzień: rotacja soli przed liczeniem limitu
    try:
        return _roll(conn, sid, body.booth_id)
    except _LimitReached:
        st = game_state(conn, sid)
        return JSONResponse({"detail": BOOTH_LIMIT, "attempts_left": 0, "booth_left": 0, "bonus_attempts": 0,
                             "best_today": st["best_today"]},
                            status_code=429)


def _roll(conn: sqlite3.Connection, sid: str, booth_id: str) -> dict:
    today = config.today()
    with db.tx(conn):
        booth = conn.execute("SELECT * FROM booths WHERE id=?", (booth_id,)).fetchone()
        if booth is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        sess = conn.execute("SELECT * FROM game_sessions WHERE session_id=?", (sid,)).fetchone()
        if (sess["pass_booth"] != booth["id"] or not sess["pass_until"] or sess["pass_until"] <= config.now_iso()
                or not sess["device_key"]):
            raise HTTPException(403, SCAN_AGAIN)
        key = sess["device_key"]
        row = conn.execute("SELECT best FROM game_attempts WHERE session_id=? AND date=?", (sid, today)).fetchone()
        prev_best = row["best"] if row else 0
        pool = booth_pool(conn, key, sess["device_ext_key"], booth["id"], sid, today)
        bonus = sess["bonus_attempts"]
        if pool <= 0 and bonus <= 0:
            raise _LimitReached
        # Najpierw pula stanowiska (5 na dobę), potem dodatkowe próby (w tej samej transakcji). Wiersz dnia zawsze
        # istnieje (do best); licznik puli idzie do booth_plays.
        from_pool = 1 if pool > 0 else 0
        conn.execute("INSERT INTO game_attempts(session_id,date,attempts) VALUES(?,?,?) "
                     "ON CONFLICT(session_id,date) DO UPDATE SET attempts=attempts+?", (sid, today, from_pool, from_pool))
        if from_pool:
            conn.execute("INSERT INTO booth_plays(device_key,booth_id,date,session_id,attempts,ext_key) VALUES(?,?,?,?,1,?) "
                         "ON CONFLICT(device_key,booth_id,date,session_id) DO UPDATE SET attempts=attempts+1, "
                         "ext_key=excluded.ext_key", (key, booth["id"], today, sid, sess["device_ext_key"] or key))
            pool -= 1
        else:
            conn.execute("UPDATE game_sessions SET bonus_attempts=bonus_attempts-1 WHERE session_id=?", (sid,))
            bonus -= 1
        conn.execute("UPDATE booths SET rolls_count=rolls_count+1 WHERE id=?", (booth["id"],))
        has_won = bool(sess["has_won"])
        old = booth["current_genotype"]
        armed = testing.consume_arm(sid)  # trafienie z narzędzi testowych ma seq 0 i nie liczy się do numeracji
        won = dict.fromkeys(WON_FIELDS)
        if armed or (not has_won and game.is_win()):
            db.record_win(conn, booth["id"], sid=sid, is_test=armed)
            conn.execute("UPDATE game_sessions SET has_won=1 WHERE session_id=?", (sid,))
            st = game_state(conn, sid)
            won = {k: st[k] for k in WON_FIELDS}
            matches, player, has_won, win = len(old), old, True, True
        else:
            matches, player = game.roll(old)
            win = False
        best = max(prev_best, matches)
        conn.execute("UPDATE game_attempts SET best=? WHERE session_id=? AND date=?", (best, sid, today))
    return {"matches": matches, "win": win, "player_genotype": player, "booth_genotype": old,
            "attempts_left": pool + bonus, "booth_left": pool, "bonus_attempts": bonus, "has_won": has_won, "best_today": best,
            **won}
