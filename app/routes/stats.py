"""Statystyki na żywo (publiczne) i wspólne agregaty dla podsumowań admina."""
from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends

from .. import config, db

router = APIRouter()


def _faculty_rows(conn: sqlite3.Connection, date: str | None) -> list[dict]:
    """Wszystkie wydziały ze słownika (w jego kolejności) z liczbą punktów (LD) i podziałem na kategorie.
    ``date`` = doba Europe/Warsaw."""
    where, args = "", ()
    if date:
        where, args = "WHERE created_at>=? AND created_at<?", config.day_bounds(date)
    per: dict[str, dict[str, int]] = {}
    for r in conn.execute(f"SELECT faculty, category, COUNT(*) n FROM donors_stats {where} GROUP BY faculty, category", args):
        per.setdefault(r["faculty"], {})[r["category"]] = r["n"]
    out = []
    for f in db.get_dictionary(conn)["faculties"]:
        cats = {k: per.get(f["code"], {}).get(k, 0) for k in config.CUP_CATEGORIES}
        out.append({"code": f["code"], "name": f["name"], "count": sum(cats.values()), **cats})
    return out


def faculty_counts(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    """Wydziały malejąco wg liczby punktów. Remis: kolejność słownika (sort jest stabilny)."""
    return sorted(_faculty_rows(conn, date), key=lambda r: -r["count"])


def _wz(ld: int, ls: int) -> float:
    """WZ = LD / LS * 100 zaokrąglone połówkami w górę do 3 miejsc (dziesiętnie, bez błędu float: 10/3200 -> 0.313)."""
    return float((Decimal(ld * 100) / Decimal(ls)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def cup(conn: sqlite3.Connection, date: str | None = None) -> dict:
    """Puchar Dawcy PWr (§4 regulaminu): WZ = LD / LS * 100, zaokrąglone do 3 miejsc po przecinku; wydziały z LD >= 10
    (``qualified``) są przed resztą. Kolejność: WZ, potem LD (``registered``), potem liczba punktów kategorii nowy,
    potem wcześniejszy czas ostatniego punktu (brak punktów = na końcu). ``rank`` tylko dla kwalifikowanych.
    ``ranking``: wydziały z LS, bez „Inne”. ``unranked``: wydziały bez LS oraz „Inne”."""
    students = db.get_students(conn)
    where, args = "", ()
    if date:
        where, args = "WHERE created_at>=? AND created_at<?", config.day_bounds(date)
    last_at = dict(conn.execute(f"SELECT faculty, MAX(created_at) FROM donors_stats {where} GROUP BY faculty", args).fetchall())
    ranking, unranked = [], []
    for f in _faculty_rows(conn, date):
        cats = {k: f[k] for k in config.CUP_CATEGORIES}
        n = students["counts"].get(f["code"])
        if n and f["code"] != db.OTHER_FACULTY["code"]:
            ranking.append({"code": f["code"], "name": f["name"], "registered": f["count"], "students": n,
                            "wz": _wz(f["count"], n), "qualified": f["count"] >= config.CUP_MIN_POINTS,
                            **cats})
        else:
            unranked.append({"code": f["code"], "name": f["name"], "registered": f["count"], **cats})
    ranking.sort(key=lambda r: (not r["qualified"], -r["wz"], -r["registered"], -r["nowy"],
                                last_at.get(r["code"]) is None, last_at.get(r["code"]) or ""))
    out, place = [], 0
    for r in ranking:
        place += r["qualified"]
        out.append({"rank": place if r["qualified"] else None, **r})
    return {"ranking": out, "unranked": unranked, "source": students["source"]}


@router.get("/api/stats/cup")
def cup_route(conn: sqlite3.Connection = Depends(db.get_db)):
    return {**cup(conn), "cup_deadline": config.iso(config.cup_deadline()), "cup_closed": config.cup_closed(),
            "cup_closed_message": config.cup_closed_message()}


@router.get("/api/stats/live")
def live(conn: sqlite3.Connection = Depends(db.get_db)):
    total = conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0]
    cats = db.category_counts(conn)
    # Stanowisko „Zajęcia” (is_lecture) nie jest na liście stoisk; jego próby i trafienia liczą się w sumach gry.
    per_booth: dict[str, dict[str, int]] = {}  # jeden GROUP BY zamiast zapytania na każde stoisko
    for r in conn.execute("SELECT booth_id, category, COUNT(*) n FROM donors_stats GROUP BY booth_id, category"):
        per_booth.setdefault(r["booth_id"], {})[r["category"]] = r["n"]
    booths = []
    for b in conn.execute("SELECT id, name, matches_count, rolls_count FROM booths WHERE is_lecture=0 ORDER BY id"):
        c = {**dict.fromkeys(config.CUP_CATEGORIES, 0), **per_booth.get(b["id"], {})}
        booths.append({"id": b["id"], "name": b["name"], "registered": sum(c.values()), **c,
                       "matches_count": b["matches_count"], "rolls_count": b["rolls_count"]})
    faculties = _faculty_rows(conn, None)  # kolejność słownika: /statystyki nie jest rankingiem
    game = conn.execute("SELECT COALESCE(SUM(rolls_count),0) r, COALESCE(SUM(matches_count),0) m FROM booths").fetchone()
    players = conn.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
    return {"total": total, **{f"total_{k}": v for k, v in cats.items()}, "faculties": faculties, "booths": booths,
            "game": {"rolls": game["r"], "matches": game["m"], "players": players}}
