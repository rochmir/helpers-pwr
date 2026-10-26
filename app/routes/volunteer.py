"""Wolontariusz: logowanie kontem (login + hasło) na wybrane stoisko, generowanie i anulowanie kodów."""
from __future__ import annotations

import secrets
import sqlite3

from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import auth, captcha, cards, config, db

router = APIRouter(prefix="/api/volunteer")
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


class AuthIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)
    booth_id: str = Field(max_length=40)
    cf_turnstile: str | None = Field(None, max_length=4096)


class GenerateIn(BaseModel):
    booth_id: str | None = Field(None, max_length=40)
    kind: str = Field("potential", max_length=16)
    card_number: str | None = Field(None, max_length=120)
    card_date: str | None = Field(None, max_length=10)


def _code_view(row: sqlite3.Row) -> dict:
    return {"code": row["code"], "status": row["status"], "kind": row["kind"], "created_at": row["created_at"],
            "expires_at": config.expiry_of(row["created_at"])}


@router.post("/auth")
def volunteer_auth(body: AuthIn, response: Response, conn: sqlite3.Connection = Depends(db.get_db)):
    captcha.require(body.cf_turnstile)
    login = body.login.strip().lower()
    key = "vol:" + login[:64]
    auth.throttle.check(key)
    account = conn.execute("SELECT * FROM volunteers WHERE login=?", (login,)).fetchone()
    ok = False
    if account is not None:
        try:
            ok = db.hasher.verify(account["password_hash"], body.password)
        except (VerifyMismatchError, InvalidHashError):
            ok = False
    if not ok:
        auth.throttle.fail(key)
        raise HTTPException(401, "Błędny login lub hasło.")
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (body.booth_id.strip().lower(),)).fetchone()
    if booth is None:
        raise HTTPException(404, "Wybierz stoisko z listy.")
    auth.throttle.reset(key)
    auth.set_staff_cookie(response, {"role": "volunteer", "booth": booth["id"], "login": login,
                                     "ph": auth.hash_tag(account["password_hash"])})
    return {"booth": {"id": booth["id"], "name": booth["name"]}}


@router.post("/logout")
def logout(response: Response):
    auth.clear_staff_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(booth_id: str | None = None, staff: dict = Depends(auth.require_volunteer),
       conn: sqlite3.Connection = Depends(db.get_db)):
    if staff["role"] == "admin" and not booth_id:
        # Admin otwiera panel wolontariusza bez wybranego stoiska — frontend pokaże listę.
        return {"role": "admin", "booth": None, "registered_count": 0, "registered_potential": 0, "registered_actual": 0, "matches_count": 0,
                "rolls_count": 0, "codes": []}
    bid = auth.resolve_booth(staff, booth_id)
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    db.expire_codes(conn)
    codes = conn.execute("SELECT * FROM registration_codes WHERE booth_id=? ORDER BY created_at DESC, rowid DESC LIMIT 20",
                         (bid,)).fetchall()
    counts = {r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM donors_stats WHERE booth_id=? GROUP BY kind", (bid,))}
    potential, actual = counts.get("potential", 0), counts.get("actual", 0)
    return {"role": staff["role"], "booth": {"id": booth["id"], "name": booth["name"]},
            "registered_count": potential + actual, "registered_potential": potential,
            "registered_actual": actual, "matches_count": booth["matches_count"],
            "rolls_count": booth["rolls_count"], "codes": [_code_view(c) for c in codes]}


@router.post("/generate-code")
def generate_code(body: GenerateIn, staff: dict = Depends(auth.require_volunteer),
                  conn: sqlite3.Connection = Depends(db.get_db)):
    bid = auth.resolve_booth(staff, body.booth_id)
    if body.kind not in ("potential", "actual"):
        raise HTTPException(422, "Niepoprawny typ kodu.")
    chash = None
    if body.kind == "actual":
        try:
            chash = cards.card_hash(body.card_number or "", body.card_date or "")
        except ValueError:
            raise HTTPException(422, "Dawca faktyczny: podaj numer legitymacji (do 40 znaków) i datę jej wydania.")
    ts = config.now_iso()
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (bid,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        if chash:
            db.expire_codes(conn)
            if conn.execute("SELECT 1 FROM actual_donor_cards WHERE card_hash=?", (chash,)).fetchone():
                raise HTTPException(409, "Ta legitymacja jest już zarejestrowana w systemie.")
            if conn.execute("SELECT 1 FROM registration_codes WHERE card_hash=? AND status='ACTIVE'", (chash,)).fetchone():
                raise HTTPException(409, "Dla tej legitymacji jest już aktywny kod.")
        for _ in range(20):
            code = f"{bid.upper()}-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if conn.execute("SELECT 1 FROM registration_codes WHERE code=?", (code,)).fetchone() is None:
                conn.execute("INSERT INTO registration_codes(code,booth_id,status,created_at,kind,card_hash) "
                             "VALUES(?,?,'ACTIVE',?,?,?)", (code, bid, ts, body.kind, chash))
                break
        else:
            raise HTTPException(503, "Nie udało się wygenerować kodu. Spróbuj ponownie.")
    return {"code": code, "kind": body.kind, "expires_at": config.expiry_of(ts), "confirm_path": f"/potwierdz?kod={code}"}


@router.post("/codes/{code}/cancel")
def cancel_code(code: str, staff: dict = Depends(auth.require_volunteer),
                conn: sqlite3.Connection = Depends(db.get_db)):
    return cancel(conn, code.strip().upper(), staff)


def cancel(conn: sqlite3.Connection, code: str, staff: dict) -> dict:
    """Anulowanie kodu ACTIVE (status EXPIRED). Wolontariusz tylko na swoim stoisku."""
    with db.tx(conn):
        db.expire_codes(conn)
        row = conn.execute("SELECT * FROM registration_codes WHERE code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "Nie ma takiego kodu.")
        if staff["role"] == "volunteer" and row["booth_id"] != staff["booth"]:
            raise HTTPException(403, "To kod z innego stoiska.")
        if row["status"] != "ACTIVE":
            raise HTTPException(409, "Kod nie jest już aktywny.")
        conn.execute("UPDATE registration_codes SET status='EXPIRED' WHERE code=?", (code,))
    return {"ok": True}
