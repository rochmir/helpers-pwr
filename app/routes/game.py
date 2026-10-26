"""Gra: stan stoiska, sesja gracza, przepustka ze skanu QR, losowanie genotypu."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import auth, captcha, config, db, game, qrtoken, testing

router = APIRouter()
SCAN_AGAIN = "Zeskanuj ponownie kod QR ze stoiska."


class _LimitReached(Exception):
    pass


class SessionIn(BaseModel):
    cf_turnstile: str | None = Field(None, max_length=4096)


class RollIn(BaseModel):
    booth_id: str = Field(max_length=40)


class EnterIn(BaseModel):
    booth_id: str = Field(max_length=40)
    t: str = Field(max_length=64)


def game_state(conn: sqlite3.Connection, sid: str) -> dict:
    """Stan gracza: próby (dzienne + bonusowe), najlepszy wynik dnia, ważna przepustka."""
    s = conn.execute("SELECT has_won, bonus_attempts, pass_booth, pass_until, won_genotype, won_at FROM game_sessions WHERE session_id=?",
                     (sid,)).fetchone()
    a = conn.execute("SELECT attempts, best FROM game_attempts WHERE session_id=? AND date=?",
                     (sid, config.today())).fetchone()
    used = a["attempts"] if a else 0
    pass_ok = bool(s["pass_booth"] and s["pass_until"] and s["pass_until"] > config.now_iso())
    return {"attempts_left": max(0, config.DAILY_ATTEMPTS - used) + s["bonus_attempts"],
            "bonus_attempts": s["bonus_attempts"], "has_won": bool(s["has_won"]),
            "best_today": a["best"] if a else 0, "pass_booth": s["pass_booth"] if pass_ok else None,
            "won_genotype": s["won_genotype"], "won_at": s["won_at"]}


def attempts_left(conn: sqlite3.Connection, sid: str) -> int:
    return game_state(conn, sid)["attempts_left"]


@router.get("/api/booth/{booth_id}/state")
def booth_state(booth_id: str, staff: dict | None = Depends(auth.optional_staff),
                conn: sqlite3.Connection = Depends(db.get_db)):
    b = conn.execute("SELECT * FROM booths WHERE id=?", (booth_id,)).fetchone()
    if b is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    out = {"id": b["id"], "name": b["name"], "genotype": b["current_genotype"],
           "genotype_updated_at": b["genotype_updated_at"], "matches_count": b["matches_count"],
           "rolls_count": b["rolls_count"], "play_path": None, "qr_seconds_left": None}
    # Ważny link do gry (aktualny token QR) dostaje tylko personel tego stoiska; publicznie go nie ma.
    if staff and (staff["role"] == "admin" or staff.get("booth") == b["id"]):
        out["play_path"] = f"/graj?stoisko={b['id']}&t={qrtoken.current(b['id'])}"
        out["qr_seconds_left"] = qrtoken.seconds_to_change()
    return out


@router.post("/api/game/session")
def create_session(body: SessionIn, request: Request, response: Response,
                   sid: str | None = Depends(auth.optional_game_session),
                   conn: sqlite3.Connection = Depends(db.get_db)):
    if sid is not None:  # ważna sesja, bez captchy
        token = request.cookies.get(auth.GAME_COOKIE) or request.headers.get("X-Game-Token")
        auth.set_game_cookie(response, token)
    else:
        captcha.require(body.cf_turnstile)
        sid, token = auth.new_game_token()
        conn.execute("INSERT INTO game_sessions(session_id,created_at) VALUES(?,?)", (sid, config.now_iso()))
        auth.set_game_cookie(response, token)
    return {"token": token, **game_state(conn, sid)}


@router.get("/api/game/me")
def me(sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    return game_state(conn, sid)


@router.post("/api/game/enter")
def enter(body: EnterIn, sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    """Przepustka na stoisko po zeskanowaniu aktualnego kodu QR; kolejne skanowanie ją odnawia."""
    if conn.execute("SELECT 1 FROM booths WHERE id=?", (body.booth_id,)).fetchone() is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    if not qrtoken.valid(body.booth_id, body.t):
        raise HTTPException(403, "Ten kod QR wygasł. " + SCAN_AGAIN)
    until = config.iso(config.now() + timedelta(minutes=config.PASS_MINUTES))
    conn.execute("UPDATE game_sessions SET pass_booth=?, pass_until=? WHERE session_id=?", (body.booth_id, until, sid))
    return {"ok": True, "pass_until": until}


@router.post("/api/game/roll")
def roll(body: RollIn, sid: str = Depends(auth.game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    try:
        return _roll(conn, sid, body.booth_id)
    except _LimitReached:
        st = game_state(conn, sid)
        return JSONResponse({"detail": "Wykorzystano dzisiejsze próby. Wróć jutro!", "attempts_left": 0,
                             "bonus_attempts": 0, "best_today": st["best_today"]}, status_code=429)


def _roll(conn: sqlite3.Connection, sid: str, booth_id: str) -> dict:
    today = config.today()
    daily = config.DAILY_ATTEMPTS
    with db.tx(conn):
        booth = conn.execute("SELECT * FROM booths WHERE id=?", (booth_id,)).fetchone()
        if booth is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        sess = conn.execute("SELECT * FROM game_sessions WHERE session_id=?", (sid,)).fetchone()
        row = conn.execute("SELECT attempts, best FROM game_attempts WHERE session_id=? AND date=?", (sid, today)).fetchone()
        used = row["attempts"] if row else 0
        prev_best = row["best"] if row else 0
        bonus = sess["bonus_attempts"]
        if used >= daily and bonus <= 0:
            raise _LimitReached
        if sess["pass_booth"] != booth["id"] or not sess["pass_until"] or sess["pass_until"] <= config.now_iso():
            raise HTTPException(403, SCAN_AGAIN)
        # Najpierw pula dzienna, potem bonus (w tej samej transakcji).
        if used < daily:
            conn.execute("INSERT INTO game_attempts(session_id,date,attempts) VALUES(?,?,1) "
                         "ON CONFLICT(session_id,date) DO UPDATE SET attempts=attempts+1", (sid, today))
            used += 1
        else:
            conn.execute("UPDATE game_sessions SET bonus_attempts=bonus_attempts-1 WHERE session_id=?", (sid,))
            bonus -= 1
        conn.execute("UPDATE booths SET rolls_count=rolls_count+1 WHERE id=?", (booth["id"],))
        has_won = bool(sess["has_won"])
        old = booth["current_genotype"]
        armed = testing.consume_arm(sid)  # trafienie z narzędzi testowych nie wchodzi do losowania
        won_at = None
        if armed or (not has_won and game.is_win()):
            db.record_win(conn, booth["id"], sid=sid, is_test=armed)
            won_at = conn.execute("SELECT won_at FROM game_sessions WHERE session_id=?", (sid,)).fetchone()[0]
            conn.execute("UPDATE game_sessions SET has_won=1 WHERE session_id=?", (sid,))
            matches, player, has_won, win = len(old), old, True, True
        else:
            matches, player = game.roll(old)
            win = False
        best = max(prev_best, matches)
        conn.execute("UPDATE game_attempts SET best=? WHERE session_id=? AND date=?", (best, sid, today))
    return {"matches": matches, "win": win, "player_genotype": player, "booth_genotype": old,
            "attempts_left": max(0, daily - used) + bonus, "bonus_attempts": bonus,
            "has_won": has_won, "best_today": best, "won_at": won_at}
