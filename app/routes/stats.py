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


def actual_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Faktyczni dawcy wg wydziału (``cup_actual_counts``). Licznik nie ma dat, więc tylko dla widoku łącznego."""
    return {r["faculty"]: r["actual"] for r in conn.execute("SELECT faculty, actual FROM cup_actual_counts")}


def faculty_counts(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """Wydziały malejąco wg liczby punktów. Remis: kolejność słownika (sort jest stabilny)."""
    return sorted(_faculty_rows(conn, date), key=lambda r: -r["count"])


def cup(conn: sqlite3.Connection, date: str | None = None) -> dict:
    """Puchar Dawcy PWr: ranking wg Wskaźnika Zaangażowania WZ = LD / LS * 100 (§4 regulaminu), tylko wydziały
    z liczbą studentów (LS), bez „Inne”. Remis WZ (do 2 miejsc po przecinku): wyższe LD, potem kolejność słownika.
    ``registered`` to LD (punkty). ``unranked``: wydziały bez LS oraz „Inne”.
    Bez ``date`` każda pozycja ma też ``actual`` (faktyczni dawcy, z ``cup_actual_counts``) i ``potential``
    (``registered - actual``); wpisy bez podziału liczą się jako nowi. Licznik nie ma dat, więc w widoku
    dziennym (``date``) podziału nie ma."""
    split = {} if date else actual_counts(conn)

    def parts(code: str, ld: int) -> dict:
        if date:
            return {}
        a = max(0, min(split.get(code, 0), ld))
        return {"actual": a, "potential": ld - a}
    students = db.get_students(conn)
    ranking, unranked = [], []
    for f in _faculty_rows(conn, date):
        n = students["counts"].get(f["code"])
        if n and f["code"] != db.OTHER_FACULTY["code"]:
            ranking.append({"code": f["code"], "name": f["name"], "registered": f["count"], "students": n,
                            "wz": round(f["count"] / n * 100, 2), **parts(f["code"], f["count"])})
        else:
            unranked.append({"code": f["code"], "name": f["name"], "registered": f["count"],
                             **parts(f["code"], f["count"])})
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
    # Stanowisko „Zajęcia” (is_lecture) nie jest na liście stoisk; jego próby i trafienia liczą się w sumach gry.
    booths = conn.execute(
        "SELECT b.id, b.name, b.matches_count, b.rolls_count, "
        "(SELECT COUNT(*) FROM registration_codes c WHERE c.booth_id=b.id AND c.status='USED') AS registered, "
        "(SELECT COUNT(*) FROM registration_codes c WHERE c.booth_id=b.id AND c.status='USED' AND c.kind='actual') AS actual "
        "FROM booths b WHERE b.is_lecture=0 ORDER BY b.id")
    split = actual_counts(conn)
    faculties = []
    for f in _faculty_rows(conn, None):  # kolejność słownika: /statystyki nie jest rankingiem
        a = max(0, min(split.get(f["code"], 0), f["count"]))
        faculties.append({**f, "actual": a, "potential": f["count"] - a})
    game = conn.execute("SELECT COALESCE(SUM(rolls_count),0) r, COALESCE(SUM(matches_count),0) m FROM booths").fetchone()
    players = conn.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
    return {"total": total, "total_potential": kinds.get("potential", 0), "total_actual": kinds.get("actual", 0),
            "faculties": faculties,
            "booths": [{"id": b["id"], "name": b["name"], "registered": b["registered"], "actual": b["actual"],
                        "matches_count": b["matches_count"], "rolls_count": b["rolls_count"]} for b in booths],
            "game": {"rolls": game["r"], "matches": game["m"], "players": players}}
