"""Statystyki na żywo (publiczne) i wspólne agregaty dla podsumowań admina."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import db

router = APIRouter()


def faculty_counts(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """Wszystkie wydziały ze słownika: potencjalni, faktyczni i razem (count = razem), malejąco.
    Remis: kolejność słownika (sort jest stabilny)."""
    where, args = ("WHERE registered_date=?", (date,)) if date else ("", ())
    counts: dict[tuple[str, str], int] = {}
    for r in conn.execute(f"SELECT faculty, kind, COUNT(*) n FROM donors_stats {where} GROUP BY faculty, kind", args):
        counts[(r["faculty"], r["kind"])] = r["n"]
    rows = []
    for f in db.get_dictionary(conn)["faculties"]:
        p, a = counts.get((f["code"], "potential"), 0), counts.get((f["code"], "actual"), 0)
        rows.append({"code": f["code"], "name": f["name"], "potential": p, "actual": a, "total": p + a, "count": p + a})
    return sorted(rows, key=lambda r: -r["count"])


@router.get("/api/stats/live")
def live(conn: sqlite3.Connection = Depends(db.get_db)):
    total = conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0]
    total_actual = conn.execute("SELECT COUNT(*) FROM donors_stats WHERE kind='actual'").fetchone()[0]
    booths = conn.execute(
        "SELECT b.id, b.name, b.matches_count, b.rolls_count, "
        "(SELECT COUNT(*) FROM donors_stats d WHERE d.booth_id=b.id) AS registered FROM booths b ORDER BY b.id")
    game = conn.execute("SELECT COALESCE(SUM(rolls_count),0) r, COALESCE(SUM(matches_count),0) m FROM booths").fetchone()
    players = conn.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
    return {"total": total, "total_potential": total - total_actual, "total_actual": total_actual, "faculties": faculty_counts(conn),
            "booths": [{"id": b["id"], "name": b["name"], "registered": b["registered"],
                        "matches_count": b["matches_count"], "rolls_count": b["rolls_count"]} for b in booths],
            "game": {"rolls": game["r"], "matches": game["m"], "players": players}}
