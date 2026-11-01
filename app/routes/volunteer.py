"""Wolontariusz: licznik i lista tokenów rejestracyjnych wybranego stoiska, generowanie i anulowanie tokenów."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, config, db

router = APIRouter(prefix="/api/volunteer")


class GenerateIn(BaseModel):
    booth_id: str | None = Field(None, max_length=40)
    kind: str = Field("potential", max_length=16)


def _code_view(row: sqlite3.Row) -> dict:
    return {"code": row["code"], "status": row["status"], "kind": row["kind"], "created_at": row["created_at"],
            "expires_at": config.expiry_of(row["created_at"])}


def _cup_info() -> dict:
    return {"cup_closed": config.cup_closed(), "cup_closed_message": config.cup_closed_message(),
            "cup_deadline": config.iso(config.cup_deadline())}


@router.get("/me")
def me(booth_id: str | None = None, staff: dict = Depends(auth.require_volunteer),
       conn: sqlite3.Connection = Depends(db.get_db)):
    if staff["role"] == "admin" and not (booth_id or staff["booth"]):
        # Admin bez wybranego stoiska: pusty widok, frontend pokaże wybór.
        return {"role": "admin", "booth": None, "registered_count": 0, "registered_potential": 0, "registered_actual": 0, "matches_count": 0,
                "rolls_count": 0, "codes": [], **_cup_info()}
    bid = auth.resolve_booth(staff, booth_id)
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    db.expire_codes(conn)
    codes = db.list_codes(conn, booth_id=bid)
    counts = db.used_counts(conn, bid)  # donors_stats nie trzyma stoiska ani typu (§3.4 Pucharu)
    potential, actual = counts.get("potential", 0), counts.get("actual", 0)
    return {"role": staff["role"], "booth": {"id": booth["id"], "name": booth["name"]},
            "registered_count": potential + actual, "registered_potential": potential,
            "registered_actual": actual, "matches_count": booth["matches_count"],
            "rolls_count": booth["rolls_count"], "codes": [_code_view(c) for c in codes], **_cup_info()}


@router.post("/generate-code")
def generate_code(body: GenerateIn, staff: dict = Depends(auth.require_volunteer),
                  conn: sqlite3.Connection = Depends(db.get_db)):
    """Token rejestracyjny (kod OTP) po weryfikacji wymazu albo legitymacji dawcy faktycznego (jej numeru nie zapisujemy)."""
    # Kod promo (dodatkowe próby) nie zależy od terminu Pucharu; token rejestracyjny po terminie = 410.
    if body.kind != "promo" and config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    bid = auth.resolve_booth(staff, body.booth_id)
    if body.kind not in ("potential", "actual", "promo"):
        raise HTTPException(422, "Niepoprawny typ tokenu.")
    ts = config.now_iso()
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (bid,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        code = db.unique_code(conn, bid)
        if code is None:
            raise HTTPException(503, "Nie udało się wygenerować tokenu. Spróbuj ponownie.")
        if body.kind == "promo":
            conn.execute("INSERT INTO promo_codes(code,booth_id,status,created_at) VALUES(?,?,'ACTIVE',?)", (code, bid, ts))
        else:
            conn.execute("INSERT INTO registration_codes(code,booth_id,status,created_at,kind) VALUES(?,?,'ACTIVE',?,?)",
                         (code, bid, ts, body.kind))
    return {"code": code, "kind": body.kind, "expires_at": config.expiry_of(ts), "confirm_path": f"/potwierdz?kod={code}"}


@router.post("/codes/{code}/cancel")
def cancel_code(code: str, staff: dict = Depends(auth.require_volunteer),
                conn: sqlite3.Connection = Depends(db.get_db)):
    return cancel(conn, code.strip().upper(), staff)


def cancel(conn: sqlite3.Connection, code: str, staff: dict) -> dict:
    """Anulowanie tokenu ACTIVE (status EXPIRED). Wolontariusz tylko na swoim stoisku."""
    with db.tx(conn):
        db.expire_codes(conn)
        found = db.find_code(conn, code)
        if found is None:
            raise HTTPException(404, "Nie ma takiego tokenu.")
        table, row = found
        if staff["role"] == "volunteer" and not staff["booth"]:
            raise HTTPException(409, "Wybierz stoisko.")
        if staff["role"] == "volunteer" and row["booth_id"] != staff["booth"]:
            raise HTTPException(403, "To token z innego stoiska.")
        if row["status"] != "ACTIVE":
            raise HTTPException(409, "Token nie jest już aktywny.")
        conn.execute(f"UPDATE {table} SET status='EXPIRED' WHERE code=?", (code,))
    return {"ok": True}
