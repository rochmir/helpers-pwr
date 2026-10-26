"""Losowanie finałowe (/api/admin/raffle): jeden genotyp spośród wszystkich prawdziwych trafień 10/10.

Przechowujemy wyłącznie anonimowy wzór, stoisko i czas trafienia — bez nicków i adresów IP."""
from __future__ import annotations

import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, config, db

router = APIRouter(prefix="/api/admin/raffle")

# Trafienia testowe (arm-win, force-win) nie biorą udziału w losowaniu.
ENTRIES_SQL = ("SELECT h.genotype, h.booth_id, b.name AS booth_name, h.matched_at FROM genotype_history h "
               "LEFT JOIN booths b ON b.id=h.booth_id WHERE h.matched_at IS NOT NULL AND h.is_test=0 "
               "ORDER BY h.matched_at, h.genotype")


def _entries(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(ENTRIES_SQL)]


def _draws(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT d.genotype, d.drawn_at, h.booth_id, h.matched_at FROM raffle_draws d "
                        "JOIN genotype_history h ON h.genotype=d.genotype ORDER BY d.id")
    return [dict(r) for r in rows]


@router.get("")
def overview(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    entries = _entries(conn)
    return {"entries_count": len(entries), "entries": entries, "draws": _draws(conn)}


@router.post("/draw")
def draw(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Losuje równomiernie spośród jeszcze niewylosowanych trafień (ponowne losowanie, gdy zwycięzca się nie zgłosi)."""
    with db.tx(conn):
        drawn = {r[0] for r in conn.execute("SELECT genotype FROM raffle_draws")}
        eligible = [e for e in _entries(conn) if e["genotype"] not in drawn]
        if not eligible:
            raise HTTPException(409, "Brak trafień do wylosowania.")
        pick = secrets.choice(eligible)
        ts = config.now_iso()
        conn.execute("INSERT INTO raffle_draws(genotype,drawn_at) VALUES(?,?)", (pick["genotype"], ts))
    return {"genotype": pick["genotype"], "drawn_at": ts, "booth_id": pick["booth_id"],
            "booth_name": pick["booth_name"], "matched_at": pick["matched_at"],
            "remaining": len(eligible) - 1}
