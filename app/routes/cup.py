"""Puchar Dawcy PWr: słownik, odbiór kodu QR od wolontariusza (claim) i oddanie głosu; kategoria „post” = +5 prób."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, config, db, qrtoken
from .game import attempts_left

router = APIRouter()
BAD_QR = "Nieprawidłowy kod QR. Podejdź do stanowiska po nowy kod."
REVOKED_QR = "Ten kod jest już nieaktualny. Podejdź do stanowiska po nowy kod."
USED_QR = "Kod został już wykorzystany. Podejdź do stanowiska po nowy kod."
CLAIM_EXPIRED = "Czas na oddanie głosu minął. Podejdź do stanowiska po nowy kod."
ALREADY_VOTED = "Z tej przeglądarki oddano już głos w Pucharze Dawcy PWr."
POST_TAKEN = "Dodatkowe próby za post zostały już dziś odebrane."


class ClaimIn(BaseModel):
    t: str = Field(max_length=200)


class VoteIn(BaseModel):
    faculty: str = Field(max_length=32)
    study_year: str = Field(max_length=16)


def _play_path(booth_id: str) -> str:
    return f"/graj?stoisko={booth_id}&t={qrtoken.current(booth_id)}"


@router.get("/api/dictionary/faculties")
def faculties(conn: sqlite3.Connection = Depends(db.get_db)):
    return {"faculties": db.get_dictionary(conn)["faculties"],
            "study_years": [{"code": c, "label": label} for c, label in config.STUDY_YEARS]}


@router.post("/api/cup/claim")
def claim(body: ClaimIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(db.get_db)):
    """Skan kodu QR od wolontariusza. ``post``: od razu +5 prób (raz dziennie na sesję). Kategorie głosu: zapamiętuje
    ``claim`` w sesji na CUP_CLAIM_MINUTES, a głos oddaje się w ``/api/cup/vote`` (wydział i rok studiów)."""
    code = conn.execute("SELECT * FROM cup_qr_codes WHERE id=?", (body.t.strip(),)).fetchone()
    if code is None:
        raise HTTPException(400, BAD_QR)
    if code["revoked_at"]:
        raise HTTPException(410, REVOKED_QR)
    if code["scanned_at"]:
        raise HTTPException(410, USED_QR)
    booth_id, category = code["booth_id"], code["category"]
    booth = conn.execute("SELECT id, name, is_lecture FROM booths WHERE id=?", (booth_id,)).fetchone()
    if booth is None or booth["is_lecture"]:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    if category != "post" and config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    with db.tx(conn):
        sid = auth.ensure_game_session(conn, request, response)
        sess = conn.execute("SELECT cup_voted, post_bonus_date FROM game_sessions WHERE session_id=?", (sid,)).fetchone()
        # Odrzucenia wynikające z sesji sprawdzamy PRZED zużyciem kodu, żeby kod nie przepadł na darmo.
        if category == "post":
            if sess["post_bonus_date"] == config.today():
                raise HTTPException(409, POST_TAKEN)
        elif sess["cup_voted"]:
            raise HTTPException(409, ALREADY_VOTED)
        now = config.now_iso()
        cur = conn.execute("UPDATE cup_qr_codes SET scanned_at=? WHERE id=? AND scanned_at IS NULL AND revoked_at IS NULL",
                           (now, code["id"]))
        if cur.rowcount == 0:
            raise HTTPException(410, USED_QR)
        if category == "post":
            today = config.today()
            bonus = config.CATEGORY_BONUS["post"]
            conn.execute("UPDATE game_sessions SET bonus_attempts=bonus_attempts+?, post_bonus_date=? WHERE session_id=?",
                         (bonus, today, sid))
            conn.execute("UPDATE cup_qr_codes SET voted_at=? WHERE id=?", (now, code["id"]))
            return_post = True
        else:
            until = config.iso(config.now() + timedelta(minutes=config.CUP_CLAIM_MINUTES))
            conn.execute("UPDATE game_sessions SET cup_claim_booth=?, cup_claim_category=?, cup_claim_until=?, "
                         "cup_claim_code=? WHERE session_id=?", (booth["id"], category, until, code["id"], sid))
            return_post = False
    if return_post:
        return {"kind": "post", "bonus_attempts_granted": bonus, "attempts_left": attempts_left(conn, sid),
                "booth_name": booth["name"], "play_path": _play_path(booth["id"])}
    return {"kind": "vote", "category": category, "booth_name": booth["name"],
            "bonus": config.CATEGORY_BONUS[category], "claim_until": until}


@router.get("/api/cup/me")
def cup_me(sid: str | None = Depends(auth.optional_game_session), conn: sqlite3.Connection = Depends(db.get_db)):
    out = {"voted": False, "claim": None, "post_today": False, "cup_closed": config.cup_closed(),
           "cup_closed_message": config.cup_closed_message()}
    if sid is None:
        return out
    s = conn.execute("SELECT cup_voted, post_bonus_date, cup_claim_booth, cup_claim_category, cup_claim_until, "
                     "(SELECT name FROM booths WHERE id=cup_claim_booth) AS booth_name "
                     "FROM game_sessions WHERE session_id=?", (sid,)).fetchone()
    out["voted"] = bool(s["cup_voted"])
    out["post_today"] = s["post_bonus_date"] == config.today()
    if not out["voted"] and s["cup_claim_until"] and s["cup_claim_until"] > config.now_iso():
        out["claim"] = {"category": s["cup_claim_category"], "booth_name": s["booth_name"],
                        "bonus": config.CATEGORY_BONUS.get(s["cup_claim_category"], 0), "until": s["cup_claim_until"]}
    return out


@router.post("/api/cup/vote")
def vote(body: VoteIn, sid: str | None = Depends(auth.optional_game_session),
         conn: sqlite3.Connection = Depends(db.get_db)):
    """Głos wydziału: wymaga ważnego claimu z sesji. Jeden głos na sesję (``cup_voted``). Do ``donors_stats`` trafia
    wydział, kategoria, rok studiów, stoisko i czas; bez powiązania z sesją."""
    if config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    with db.tx(conn):
        s = conn.execute("SELECT cup_voted, cup_claim_booth, cup_claim_category, cup_claim_until, cup_claim_code "
                         "FROM game_sessions "
                         "WHERE session_id=?", (sid,)).fetchone() if sid else None
        if s is None:
            raise HTTPException(403, CLAIM_EXPIRED)
        if s["cup_voted"]:
            raise HTTPException(409, ALREADY_VOTED)
        if not s["cup_claim_category"] or not s["cup_claim_until"] or s["cup_claim_until"] <= config.now_iso():
            raise HTTPException(403, CLAIM_EXPIRED)
        fac = next((f for f in db.get_dictionary(conn)["faculties"] if f["code"] == body.faculty), None)
        if fac is None:
            raise HTTPException(422, "Nieznany wydział.")
        if body.study_year not in dict(config.STUDY_YEARS):
            raise HTTPException(422, "Nieznany status.")
        category, booth_id = s["cup_claim_category"], s["cup_claim_booth"]
        bonus = config.CATEGORY_BONUS[category]
        cur = conn.execute("UPDATE game_sessions SET cup_voted=1, cup_claim_booth=NULL, cup_claim_category=NULL, "
                           "cup_claim_until=NULL, cup_claim_code=NULL, bonus_attempts=bonus_attempts+? WHERE session_id=? AND cup_voted=0",
                           (bonus, sid))
        if cur.rowcount == 0:
            raise HTTPException(409, ALREADY_VOTED)
        if s["cup_claim_code"]:
            conn.execute("UPDATE cup_qr_codes SET voted_at=? WHERE id=?", (config.now_iso(), s["cup_claim_code"]))
        conn.execute("INSERT INTO donors_stats(faculty,created_at,category,study_year,booth_id) VALUES(?,?,?,?,?)",
                     (fac["code"], config.now_iso(), category, body.study_year, booth_id))
    booth = conn.execute("SELECT name FROM booths WHERE id=?", (booth_id,)).fetchone()
    return {"ok": True, "faculty": fac["code"], "faculty_name": fac["name"], "category": category,
            "booth_name": booth["name"] if booth else "", "bonus_attempts_granted": bonus,
            "attempts_left": attempts_left(conn, sid), "play_path": _play_path(booth_id)}
