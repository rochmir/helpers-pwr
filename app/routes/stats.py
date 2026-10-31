"""Statystyki na żywo (publiczne) i wspólne agregaty dla podsumowań admina."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import db

router = APIRouter()


def _faculty_rows(conn: sqlite3.Connection, date: str | None) -> list[dict]:
    """Wszystkie wydziały ze słownika (w jego kolejności): potencjalni, faktyczni i razem (count = razem)."""
    where, args = ("WHERE registered_date=?", (date,)) if date else ("", ())
    counts: dict[tuple[str, str], int] = {}
    for r in conn.execute(f"SELECT faculty, kind, COUNT(*) n FROM donors_stats {where} GROUP BY faculty, kind", args):
        counts[(r["faculty"], r["kind"])] = r["n"]
    rows = []
    for f in db.get_dictionary(conn)["faculties"]:
        p, a = counts.get((f["code"], "potential"), 0), counts.get((f["code"], "actual"), 0)
        rows.append({"code": f["code"], "name": f["name"], "potential": p, "actual": a, "total": p + a, "count": p + a})
    return rows


def faculty_counts(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """Wydziały malejąco wg liczby rejestracji. Remis: kolejność słownika (sort jest stabilny)."""
    return sorted(_faculty_rows(conn, date), key=lambda r: -r["count"])


def battle(conn: sqlite3.Connection, date: str | None = None) -> dict:
    """Bitwa Wydziałów: ranking wg rejestracji na 1000 studentów (tylko wydziały z liczbą studentów, bez „Inne”).
    Remis: więcej rejestracji, potem kolejność słownika. ``unranked``: wydziały bez liczby studentów oraz „Inne”."""
    students = db.get_students(conn)
    ranking, unranked = [], []
    for f in _faculty_rows(conn, date):
        n = students["counts"].get(f["code"])
        if n and f["code"] != db.OTHER_FACULTY["code"]:
            ranking.append({"code": f["code"], "name": f["name"], "registered": f["total"], "students": n,
                            "per_1000": round(f["total"] / n * 1000, 2)})
        else:
            unranked.append({"code": f["code"], "name": f["name"], "registered": f["total"]})
    ranking.sort(key=lambda r: (-r["per_1000"], -r["registered"]))
    return {"ranking": [{"rank": i, **r} for i, r in enumerate(ranking, 1)], "unranked": unranked,
            "source": students["source"]}


@router.get("/api/stats/battle")
def battle_route(conn: sqlite3.Connection = Depends(db.get_db)):
    return battle(conn)


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
