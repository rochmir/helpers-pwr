"""Wolontariusz: licznik i lista kodów wybranego stoiska, generowanie i anulowanie kodów."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, cards, config, db

router = APIRouter(prefix="/api/volunteer")


class GenerateIn(BaseModel):
    booth_id: str | None = Field(None, max_length=40)
    kind: str = Field("potential", max_length=16)
    card_number: str | None = Field(None, max_length=120)
    card_date: str | None = Field(None, max_length=10)


def _code_view(row: sqlite3.Row) -> dict:
    return {"code": row["code"], "status": row["status"], "kind": row["kind"], "created_at": row["created_at"],
            "expires_at": config.expiry_of(row["created_at"])}


@router.get("/me")
def me(booth_id: str | None = None, staff: dict = Depends(auth.require_volunteer),
       conn: sqlite3.Connection = Depends(db.get_db)):
    if staff["role"] == "admin" and not (booth_id or staff["booth"]):
        # Admin bez wybranego stoiska: pusty widok, frontend pokaże wybór.
        return {"role": "admin", "booth": None, "registered_count": 0, "registered_potential": 0, "registered_actual": 0, "matches_count": 0,
                "rolls_count": 0, "codes": []}
    bid = auth.resolve_booth(staff, booth_id)
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    db.expire_codes(conn)
    codes = db.list_codes(conn, booth_id=bid)
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
    if body.kind not in ("potential", "actual", "promo"):
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
        code = db.unique_code(conn, bid)
        if code is None:
            raise HTTPException(503, "Nie udało się wygenerować kodu. Spróbuj ponownie.")
        if body.kind == "promo":
            conn.execute("INSERT INTO promo_codes(code,booth_id,status,created_at) VALUES(?,?,'ACTIVE',?)", (code, bid, ts))
        else:
            conn.execute("INSERT INTO registration_codes(code,booth_id,status,created_at,kind,card_hash) "
                         "VALUES(?,?,'ACTIVE',?,?,?)", (code, bid, ts, body.kind, chash))
    return {"code": code, "kind": body.kind, "expires_at": config.expiry_of(ts), "confirm_path": f"/potwierdz?kod={code}"}


@router.post("/codes/{code}/cancel")
def cancel_code(code: str, staff: dict = Depends(auth.require_volunteer),
                conn: sqlite3.Connection = Depends(db.get_db)):
    return cancel(conn, code.strip().upper(), staff)


def cancel(conn: sqlite3.Connection, code: str, staff: dict) -> dict:
    """Anulowanie kodu ACTIVE (status EXPIRED). Wolontariusz tylko na swoim stoisku."""
    with db.tx(conn):
        db.expire_codes(conn)
        found = db.find_code(conn, code)
        if found is None:
            raise HTTPException(404, "Nie ma takiego kodu.")
        table, row = found
        if staff["role"] == "volunteer" and not staff["booth"]:
            raise HTTPException(409, "Wybierz stoisko.")
        if staff["role"] == "volunteer" and row["booth_id"] != staff["booth"]:
            raise HTTPException(403, "To kod z innego stoiska.")
        if row["status"] != "ACTIVE":
            raise HTTPException(409, "Kod nie jest już aktywny.")
        conn.execute(f"UPDATE {table} SET status='EXPIRED' WHERE code=?", (code,))
    return {"ok": True}
