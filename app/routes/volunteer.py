"""Wolontariusz: liczniki stoiska i jednorazowy kod QR do głosu w Pucharze (4 kategorie, ważny do zeskanowania)."""
from __future__ import annotations

import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, config, db
from .game import booth_open

router = APIRouter(prefix="/api/volunteer")


def _cup_info() -> dict:
    return {"cup_closed": config.cup_closed(), "cup_closed_message": config.cup_closed_message(),
            "cup_deadline": config.iso(config.cup_deadline())}


@router.get("/me")
def me(booth_id: str | None = None, staff: dict = Depends(auth.require_volunteer),
       conn: sqlite3.Connection = Depends(db.get_db)):
    if staff["role"] == "admin" and not (booth_id or staff["booth"]):
        # Admin bez wybranego stoiska: pusty widok, frontend pokaże wybór.
        return {"role": "admin", "booth": None, "registered_count": 0, "registered_nowy": 0,
                "registered_zarejestrowany": 0, "registered_faktyczny": 0, "matches_count": 0, "rolls_count": 0,
                **_cup_info()}
    bid = auth.resolve_booth(staff, booth_id)
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    counts = db.category_counts(conn, bid)
    return {"role": staff["role"], "booth": {"id": booth["id"], "name": booth["name"]},
            "registered_count": sum(counts.values()),
            **{f"registered_{k}": v for k, v in counts.items()},
            "matches_count": booth["matches_count"], "rolls_count": booth["rolls_count"], **_cup_info()}


class CupQrIn(BaseModel):
    category: str = Field(max_length=20)
    booth_id: str | None = Field(None, max_length=40)


def code_status(row: sqlite3.Row) -> str:
    """active | scanned (zeskanowany, głos jeszcze nie oddany) | voted | granted (post) | revoked."""
    if row["voted_at"]:
        return "granted" if row["category"] == "post" else "voted"
    if row["scanned_at"]:
        return "scanned"
    if row["revoked_at"]:
        return "revoked"
    return "active"


@router.post("/cup-qr")
def cup_qr(body: CupQrIn, staff: dict = Depends(auth.require_volunteer), conn: sqlite3.Connection = Depends(db.get_db)):
    """Nowy jednorazowy kod QR (bez daty ważności) dla wybranej kategorii. Kod traci ważność dopiero po zeskanowaniu;
    poprzednie niezeskanowane kody zostają ważne (wspólne konto stoiska nie blokuje się nawzajem)."""
    if body.category not in config.QR_CATEGORIES:
        raise HTTPException(422, "Niepoprawna kategoria.")
    bid = auth.resolve_booth(staff, body.booth_id)
    booth = conn.execute("SELECT * FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    if booth["is_lecture"]:
        raise HTTPException(409, "Na stanowisku Zajęcia nie ma wolontariusza, więc nie wystawia się tam kodów QR.")
    if body.category != "post" and config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    if not booth_open(booth):
        raise HTTPException(409, "Stanowisko dziś nie działa (poza datami stoiska), więc nie wystawia się tam kodów QR.")
    code, now = secrets.token_urlsafe(16), config.now_iso()
    with db.tx(conn):
        conn.execute("INSERT INTO cup_qr_codes(id,booth_id,category,issued_by,created_at) VALUES(?,?,?,?,?)",
                     (code, booth["id"], body.category, staff["login"], now))
    return {"id": code, "path": f"/potwierdz?t={code}", "category": body.category, "created_at": now,
            "status": "active", "booth": {"id": booth["id"], "name": booth["name"]}}


@router.get("/cup-qr/{code_id}")
def cup_qr_status(code_id: str, staff: dict = Depends(auth.require_volunteer),
                  conn: sqlite3.Connection = Depends(db.get_db)):
    """Stan kodu do odpytywania przez panel wolontariusza (tylko kody ze stoiska, którym wolno zarządzać)."""
    row = conn.execute("SELECT * FROM cup_qr_codes WHERE id=?", (code_id,)).fetchone()
    if row is None or (staff["role"] == "volunteer" and row["booth_id"] != staff["booth"]):
        raise HTTPException(404, "Nie ma takiego kodu.")
    return {"id": row["id"], "category": row["category"], "status": code_status(row), "created_at": row["created_at"],
            "scanned_at": row["scanned_at"], "voted_at": row["voted_at"]}
