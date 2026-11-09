"""Narzędzia testowe admina (/api/admin/test/*): wymuszenie trafienia, uzbrojenie próby, dane sztuczne, wipe."""
from __future__ import annotations

import random
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, config, db, testing
from .admin import DATE_RE
from .game import attempts_left as _attempts_left

router = APIRouter(prefix="/api/admin/test")
WIPE_CONFIRM = "USUŃ"


class ForceWinIn(BaseModel):
    booth_id: str = Field(max_length=40)


class FakeIn(BaseModel):
    count: int = Field(ge=1, le=500)
    booth_id: str | None = Field(None, max_length=40)
    date: str | None = Field(None, max_length=10)


class WipeIn(BaseModel):
    confirm: str = Field(max_length=20)


@router.post("/force-win")
def force_win(body: ForceWinIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (body.booth_id,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        old, new, _ = db.record_win(conn, body.booth_id, is_test=True)
    return {"old_genotype": old, "new_genotype": new}


@router.post("/arm-win")
def arm_win(sid: str | None = Depends(auth.optional_game_session), _: dict = Depends(auth.require_admin)):
    if sid is None:
        raise HTTPException(400, "Najpierw otwórz /graj w tej przeglądarce.")
    testing.arm(sid)
    return {"ok": True}


@router.post("/reset-my-game")
def reset_my_game(sid: str | None = Depends(auth.optional_game_session), _: dict = Depends(auth.require_admin),
                  conn: sqlite3.Connection = Depends(db.get_db)):
    if sid is None:
        raise HTTPException(400, "Najpierw otwórz /graj w tej przeglądarce.")
    with db.tx(conn):
        conn.execute("DELETE FROM game_attempts WHERE session_id=? AND date=?", (sid, config.today()))
        conn.execute("DELETE FROM booth_plays WHERE session_id=?", (sid,))
        conn.execute("UPDATE game_sessions SET has_won=0, bonus_attempts=0, won_genotype=NULL, won_at=NULL, won_token=NULL, "
                     "cup_voted=0, cup_claim_booth=NULL, cup_claim_category=NULL, cup_claim_until=NULL, "
                     "cup_claim_code=NULL, post_bonus_date=NULL WHERE session_id=?", (sid,))
    return {"ok": True, "attempts_left": _attempts_left(conn, sid)}


@router.post("/fake-registrations")
def fake_registrations(body: FakeIn, _: dict = Depends(auth.require_admin),
                       conn: sqlite3.Connection = Depends(db.get_db)):
    if body.date is not None and not DATE_RE.match(body.date):
        raise HTTPException(422, "Data w formacie RRRR-MM-DD.")
    with db.tx(conn):
        booths = [r[0] for r in conn.execute("SELECT id FROM booths WHERE is_lecture=0")]  # na Zajęciach nie ma tokenów
        if not booths:
            raise HTTPException(409, "Brak stoisk. Najpierw utwórz stoisko.")
        if body.booth_id is not None and body.booth_id not in booths:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        codes = [f["code"] for f in db.get_dictionary(conn)["faculties"]]
        years = [c for c, _ in config.STUDY_YEARS]
        # Głos (donors_stats) jak po prawdziwym głosowaniu: losowa kategoria (70/20/10), rok i stoisko; bez sesji.
        stamp = config.now_iso() if body.date is None else config.noon_iso(body.date)
        for _ in range(body.count):
            bid = body.booth_id or random.choice(booths)
            category = random.choices(config.CUP_CATEGORIES, weights=(70, 20, 10))[0]
            conn.execute("INSERT INTO donors_stats(faculty,created_at,category,study_year,booth_id) VALUES(?,?,?,?,?)",
                         (random.choice(codes), stamp, category, random.choice(years), bid))
    return {"created": body.count}


@router.post("/wipe")
def wipe(body: WipeIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    if body.confirm != WIPE_CONFIRM:
        raise HTTPException(400, f"Aby usunąć dane, wpisz „{WIPE_CONFIRM}”.")
    with db.tx(conn):
        # Dokumentów prawnych (legal_*) nie ruszamy: to treść regulaminów, nie dane testowe.
        for table in ("donors_stats", "registration_codes", "promo_codes", "game_sessions", "game_attempts", "booth_plays",
                      "genotype_history", "wins", "cup_qr_codes"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE booths SET matches_count=0, rolls_count=0")
        for r in conn.execute("SELECT id FROM booths").fetchall():
            ts, g = config.now_iso(), db.fresh_genotype(conn)
            conn.execute("UPDATE booths SET current_genotype=?, genotype_updated_at=? WHERE id=?", (g, ts, r["id"]))
            conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at) VALUES(?,?,?)", (g, r["id"], ts))
    testing.clear()
    return {"ok": True}


@router.get("/status")
def status(sid: str | None = Depends(auth.optional_game_session), _: dict = Depends(auth.require_admin),
           conn: sqlite3.Connection = Depends(db.get_db)):
    return {"armed": sid is not None and testing.is_armed(sid), "game_session": sid is not None,
            "attempts_left": _attempts_left(conn, sid) if sid is not None else None}
