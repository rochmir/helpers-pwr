"""Statystyki na żywo (publiczne) i wspólne agregaty dla podsumowań admina."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import config, db

router = APIRouter()


def _faculty_rows(conn: sqlite3.Connection, date: str | None) -> list[dict]:
    """Wszystkie wydziały ze słownika (w jego kolejności) z liczbą punktów (LD). ``date`` = doba Europe/Warsaw."""
    where, args = "", ()
    if date:
        where, args = "WHERE created_at>=? AND created_at<?", config.day_bounds(date)
    counts = {r["faculty"]: r["n"] for r in conn.execute(
        f"SELECT faculty, COUNT(*) n FROM donors_stats {where} GROUP BY faculty", args)}
    return [{"code": f["code"], "name": f["name"], "count": counts.get(f["code"], 0)}
            for f in db.get_dictionary(conn)["faculties"]]


def faculty_counts(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """Wydziały malejąco wg liczby punktów. Remis: kolejność słownika (sort jest stabilny)."""
    return sorted(_faculty_rows(conn, date), key=lambda r: -r["count"])


def cup(conn: sqlite3.Connection, date: str | None = None) -> dict:
    """Puchar Dawcy PWr: ranking wg Wskaźnika Zaangażowania WZ = LD / LS * 100 (§4 regulaminu), tylko wydziały
    z liczbą studentów (LS), bez „Inne”. Remis WZ (do 2 miejsc po przecinku): wyższe LD, potem kolejność słownika.
    ``registered`` to LD (punkty). ``unranked``: wydziały bez LS oraz „Inne”."""
    students = db.get_students(conn)
    ranking, unranked = [], []
    for f in _faculty_rows(conn, date):
        n = students["counts"].get(f["code"])
        if n and f["code"] != db.OTHER_FACULTY["code"]:
            ranking.append({"code": f["code"], "name": f["name"], "registered": f["count"], "students": n,
                            "wz": round(f["count"] / n * 100, 2)})
        else:
            unranked.append({"code": f["code"], "name": f["name"], "registered": f["count"]})
    ranking.sort(key=lambda r: (-r["wz"], -r["registered"]))
    return {"ranking": [{"rank": i, **r} for i, r in enumerate(ranking, 1)], "unranked": unranked,
            "source": students["source"]}


@router.get("/api/stats/cup")
def cup_route(conn: sqlite3.Connection = Depends(db.get_db)):
    return {**cup(conn), "cup_deadline": config.iso(config.cup_deadline()), "cup_closed": config.cup_closed(),
            "cup_closed_message": config.cup_closed_message()}


@router.get("/api/stats/live")
def live(conn: sqlite3.Connection = Depends(db.get_db)):
    total = conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0]
    kinds = db.used_counts(conn)
    booths = conn.execute(
        "SELECT b.id, b.name, b.matches_count, b.rolls_count, "
        "(SELECT COUNT(*) FROM registration_codes c WHERE c.booth_id=b.id AND c.status='USED') AS registered "
        "FROM booths b ORDER BY b.id")
    game = conn.execute("SELECT COALESCE(SUM(rolls_count),0) r, COALESCE(SUM(matches_count),0) m FROM booths").fetchone()
    players = conn.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
    return {"total": total, "total_potential": kinds.get("potential", 0), "total_actual": kinds.get("actual", 0),
            "faculties": _faculty_rows(conn, None),  # kolejność słownika: /statystyki nie jest rankingiem
            "booths": [{"id": b["id"], "name": b["name"], "registered": b["registered"],
                        "matches_count": b["matches_count"], "rolls_count": b["rolls_count"]} for b in booths],
            "game": {"rolls": game["r"], "matches": game["m"], "players": players}}
