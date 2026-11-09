"""Wolontariusz: liczniki stoiska i dynamiczny kod QR do głosu w Pucharze (4 kategorie, ważny 60 s)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, config, db, qrtoken

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


@router.get("/cup-qr")
def cup_qr(category: str, booth_id: str | None = None, staff: dict = Depends(auth.require_volunteer),
           conn: sqlite3.Connection = Depends(db.get_db)):
    """Świeży kod QR (token ważny 60 s) dla wybranej kategorii; wolontariusz pokazuje go dawcy na jego telefonie."""
    if category not in config.QR_CATEGORIES:
        raise HTTPException(422, "Niepoprawna kategoria.")
    bid = auth.resolve_booth(staff, booth_id)
    booth = conn.execute("SELECT id, name, is_lecture FROM booths WHERE id=?", (bid,)).fetchone()
    if booth is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    if booth["is_lecture"]:
        raise HTTPException(409, "Na stanowisku Zajęcia nie ma wolontariusza, więc nie wystawia się tam kodów QR.")
    if category != "post" and config.cup_closed():
        raise HTTPException(410, config.cup_closed_message())
    token, iat = qrtoken.cup_issue(booth["id"], category)
    return {"category": category, "path": f"/potwierdz?t={token}", "issued_at": iat,
            "expires_at": iat + config.CUP_QR_TTL_SECONDS, "valid_seconds": config.CUP_QR_TTL_SECONDS,
            "booth": {"id": booth["id"], "name": booth["name"]}}
