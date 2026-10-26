"""Panel admina: logowanie sekretem, stoiska, konta wolontariuszy, kody, słownik, podsumowania, eksport CSV."""
from __future__ import annotations

import csv
import io
import re
import secrets
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import auth, captcha, config, db
from . import stats, volunteer

router = APIRouter(prefix="/api/admin")
BOOTH_ID_RE = re.compile(r"^[a-z0-9]{1,20}$")
LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FACULTY_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
PASSWORD_MIN = 8
# Alfabet bez znaków łatwych do pomylenia (0/O/1/l/I).
PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class LoginIn(BaseModel):
    secret: str = Field(max_length=256)
    cf_turnstile: str | None = Field(None, max_length=4096)


class BoothIn(BaseModel):
    id: str = Field(max_length=40)
    name: str = Field(max_length=80)
    building: str = Field("", max_length=40)
    date_from: str | None = Field(None, max_length=10)
    date_to: str | None = Field(None, max_length=10)


class BoothPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    building: str | None = Field(None, max_length=40)
    date_from: str | None = Field(None, max_length=10)  # pusty napis czyści datę
    date_to: str | None = Field(None, max_length=10)


class HoursIn(BaseModel):
    hours: str = Field("", max_length=60)


def _iso_date(value: str | None) -> str | None:
    """Pusta wartość = brak daty; inaczej poprawna data ISO."""
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise HTTPException(422, "Data w formacie RRRR-MM-DD.")


def _check_range(date_from: str | None, date_to: str | None) -> None:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(422, "Data „do” nie może być wcześniejsza niż „od”.")


class VolunteerIn(BaseModel):
    login: str = Field(max_length=64)
    password: str | None = Field(None, max_length=256)


class PasswordIn(BaseModel):
    password: str | None = Field(None, max_length=256)


class Faculty(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=200)


class DictionaryIn(BaseModel):
    faculties: list[Faculty] = Field(max_length=100)


# --- sesja ----------------------------------------------------------------------
@router.post("/login")
def login(body: LoginIn, response: Response):
    captcha.require(body.cf_turnstile)
    auth.throttle.check("__admin__")
    if not auth.check_admin_secret(body.secret):
        auth.throttle.fail("__admin__")
        raise HTTPException(401, "Błędny sekret administratora.")
    auth.throttle.reset("__admin__")
    auth.set_staff_cookie(response, {"role": "admin"})
    return {"role": "admin"}


@router.post("/logout")
def logout(response: Response):
    auth.clear_staff_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(_: dict = Depends(auth.require_admin)):
    return {"role": "admin"}


# --- stoiska --------------------------------------------------------------------
@router.get("/booths")
def list_booths(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    db.expire_codes(conn)
    rows = conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM donors_stats d WHERE d.booth_id=b.id) AS registered, "
        "(SELECT COUNT(*) FROM registration_codes c WHERE c.booth_id=b.id AND c.status='ACTIVE') AS active_codes "
        "FROM booths b ORDER BY b.id")
    return [{k: r[k] for k in ("id", "name", "current_genotype", "genotype_updated_at", "matches_count",
                               "rolls_count", "registered", "active_codes", "building", "date_from", "date_to")} for r in rows]


@router.post("/booths", status_code=201)
def create_booth(body: BoothIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    bid, name = body.id.strip().lower(), body.name.strip()
    if not BOOTH_ID_RE.match(bid):
        raise HTTPException(422, "Id stoiska: 1-20 znaków, małe litery i cyfry.")
    if not name:
        raise HTTPException(422, "Nazwa stoiska nie może być pusta.")
    d_from, d_to = _iso_date(body.date_from), _iso_date(body.date_to)
    _check_range(d_from, d_to)
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (bid,)).fetchone():
            raise HTTPException(409, "Stoisko o tym id już istnieje.")
        db.create_booth(conn, bid, name, body.building.strip(), d_from, d_to)
    return {"id": bid, "name": name}


@router.patch("/booths/{booth_id}")
def patch_booth(booth_id: str, body: BoothPatch, _: dict = Depends(auth.require_admin),
                conn: sqlite3.Connection = Depends(db.get_db)):
    if body.name is not None and not body.name.strip():
        raise HTTPException(422, "Nazwa stoiska nie może być pusta.")
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (booth_id,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        if body.name is not None:
            conn.execute("UPDATE booths SET name=? WHERE id=?", (body.name.strip(), booth_id))
        if body.building is not None:
            conn.execute("UPDATE booths SET building=? WHERE id=?", (body.building.strip(), booth_id))
        cur = conn.execute("SELECT date_from, date_to FROM booths WHERE id=?", (booth_id,)).fetchone()
        d_from = _iso_date(body.date_from) if body.date_from is not None else cur["date_from"]
        d_to = _iso_date(body.date_to) if body.date_to is not None else cur["date_to"]
        _check_range(d_from, d_to)
        conn.execute("UPDATE booths SET date_from=?, date_to=? WHERE id=?", (d_from, d_to, booth_id))
    return {"ok": True}


@router.delete("/booths/{booth_id}")
def delete_booth(booth_id: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (booth_id,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        used = conn.execute("SELECT (SELECT COUNT(*) FROM donors_stats WHERE booth_id=?) + "
                            "(SELECT COUNT(*) FROM registration_codes WHERE booth_id=?)",
                            (booth_id, booth_id)).fetchone()[0]
        if used:
            raise HTTPException(409, "Stoisko ma rejestracje lub kody, więc nie można go usunąć.")
        conn.execute("DELETE FROM genotype_history WHERE booth_id=?", (booth_id,))
        conn.execute("DELETE FROM booths WHERE id=?", (booth_id,))
    return {"ok": True}


@router.post("/booths/{booth_id}/reset-genotype")
def reset_genotype(booth_id: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (booth_id,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        ts = config.now_iso()
        g = db.fresh_genotype(conn)
        conn.execute("UPDATE booths SET current_genotype=?, genotype_updated_at=? WHERE id=?", (g, ts, booth_id))
        conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at) VALUES(?,?,?)", (g, booth_id, ts))
    return {"genotype": g}


@router.get("/booth-hours")
def get_booth_hours(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return {"hours": db.get_booth_hours(conn)}


@router.put("/booth-hours")
def put_booth_hours(body: HoursIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    conn.execute("INSERT INTO settings(key,value) VALUES('booth_hours',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (body.hours.strip(),))
    return {"hours": body.hours.strip()}


# --- konta wolontariuszy --------------------------------------------------------
def _password(given: str | None) -> str:
    """Hasło podane przez admina (min. 8 znaków) albo wygenerowane losowe 12 znaków."""
    if given is None or given == "":
        return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(12))
    if len(given) < PASSWORD_MIN:
        raise HTTPException(422, f"Hasło musi mieć co najmniej {PASSWORD_MIN} znaków.")
    return given


@router.get("/volunteers")
def list_volunteers(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return [{"login": r["login"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT login, created_at FROM volunteers ORDER BY login")]


@router.post("/volunteers", status_code=201)
def create_volunteer(body: VolunteerIn, _: dict = Depends(auth.require_admin),
                     conn: sqlite3.Connection = Depends(db.get_db)):
    login = body.login.strip().lower()
    if not LOGIN_RE.match(login):
        raise HTTPException(422, "Login: 3-32 znaków, małe litery, cyfry oraz . _ -")
    password = _password(body.password)
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM volunteers WHERE login=?", (login,)).fetchone():
            raise HTTPException(409, "Konto o tym loginie już istnieje.")
        conn.execute("INSERT INTO volunteers(login,password_hash,created_at) VALUES(?,?,?)",
                     (login, db.hasher.hash(password), config.now_iso()))
    return {"login": login, "password": password}  # jedyny moment, w którym hasło jest widoczne


@router.post("/volunteers/{login}/reset-password")
def reset_volunteer_password(login: str, body: PasswordIn, _: dict = Depends(auth.require_admin),
                             conn: sqlite3.Connection = Depends(db.get_db)):
    login = login.strip().lower()
    password = _password(body.password)
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM volunteers WHERE login=?", (login,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego konta.")
        conn.execute("UPDATE volunteers SET password_hash=? WHERE login=?", (db.hasher.hash(password), login))
    return {"login": login, "password": password}


@router.delete("/volunteers/{login}")
def delete_volunteer(login: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    with db.tx(conn):
        if conn.execute("DELETE FROM volunteers WHERE login=?", (login.strip().lower(),)).rowcount == 0:
            raise HTTPException(404, "Nie ma takiego konta.")
    return {"ok": True}


# --- kody -----------------------------------------------------------------------
@router.get("/codes")
def list_codes(booth_id: str | None = None, status: str | None = None, _: dict = Depends(auth.require_admin),
               conn: sqlite3.Connection = Depends(db.get_db)):
    db.expire_codes(conn)
    where, args = [], []
    if booth_id:
        where.append("booth_id=?"); args.append(booth_id)
    if status:
        where.append("status=?"); args.append(status.upper())
    sql = "SELECT * FROM registration_codes" + (" WHERE " + " AND ".join(where) if where else "")
    rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC LIMIT 200", args)
    return [{"code": r["code"], "booth_id": r["booth_id"], "status": r["status"], "kind": r["kind"], "created_at": r["created_at"],
             "expires_at": config.expiry_of(r["created_at"]), "used_at": r["used_at"]} for r in rows]


@router.post("/codes/{code}/cancel")
def cancel_code(code: str, staff: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return volunteer.cancel(conn, code.strip().upper(), staff)


# --- słownik --------------------------------------------------------------------
@router.get("/dictionary")
def get_dictionary(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return db.get_dictionary(conn)


@router.put("/dictionary")
def put_dictionary(body: DictionaryIn, _: dict = Depends(auth.require_admin),
                   conn: sqlite3.Connection = Depends(db.get_db)):
    if not body.faculties:
        raise HTTPException(422, "Słownik musi zawierać co najmniej jeden wydział.")
    faculties, seen = [], set()
    for f in body.faculties:
        code, name = f.code.strip(), f.name.strip()
        if not FACULTY_CODE_RE.match(code):
            raise HTTPException(422, f"Niepoprawny kod wydziału: {code!r} (litery i cyfry, do 10 znaków).")
        if code in seen:
            raise HTTPException(422, f"Powtórzony kod wydziału: {code}.")
        if not name:
            raise HTTPException(422, f"Wydział {code} nie ma nazwy.")
        seen.add(code)
        faculties.append({"code": code, "name": name})
    with db.tx(conn):
        used = {r[0] for r in conn.execute("SELECT DISTINCT faculty FROM donors_stats")}
        missing = sorted(used - seen)
        if missing:
            raise HTTPException(409, "Nie można usunąć wydziałów, które mają rejestracje: " + ", ".join(missing) + ".")
        old = db.get_dictionary(conn)
        # „Inne” zawsze na końcu (nie da się go zgubić ani przesunąć).
        db.set_dictionary(conn, {"_note": old.get("_note", ""), "faculties": db.with_other_last(faculties)})
    return {"ok": True}


# --- podsumowania ---------------------------------------------------------------
@router.get("/summary")
def summary(date: str | None = None, _: dict = Depends(auth.require_admin),
            conn: sqlite3.Connection = Depends(db.get_db)):
    date = date or config.today()
    if date != "all" and not DATE_RE.match(date):
        raise HTTPException(422, "Data w formacie RRRR-MM-DD albo „all”.")
    total = conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0]
    if date == "all":
        d = None
        registered = total
        players = conn.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
        g = conn.execute("SELECT COALESCE(SUM(rolls_count),0) r, COALESCE(SUM(matches_count),0) m FROM booths").fetchone()
        rolls, matches = g["r"], g["m"]
    else:
        d = date
        registered = conn.execute("SELECT COUNT(*) FROM donors_stats WHERE registered_date=?", (d,)).fetchone()[0]
        g = conn.execute("SELECT COUNT(*) p, COALESCE(SUM(attempts),0) r FROM game_attempts WHERE date=?", (d,)).fetchone()
        players, rolls = g["p"], g["r"]
        matches = sum(1 for r in conn.execute("SELECT matched_at FROM genotype_history WHERE matched_at IS NOT NULL")
                      if config.warsaw_date(r["matched_at"]) == d)
    podium = [f for f in stats.faculty_counts(conn, d) if f["count"] > 0][:3]
    return {"scope": "all" if d is None else "day", "date": date, "registered": registered,
            "registered_total": total, "podium": podium,
            "game": {"players": players, "rolls": rolls, "matches": matches}}


@router.get("/days")
def days(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    found = {r[0] for r in conn.execute("SELECT registered_date FROM donors_stats")}
    found |= {r[0] for r in conn.execute("SELECT date FROM game_attempts")}
    found |= {config.warsaw_date(r[0]) for r in conn.execute(
        "SELECT matched_at FROM genotype_history WHERE matched_at IS NOT NULL")}
    return sorted(found, reverse=True)


@router.get("/export-csv")
def export_csv(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["id", "booth_id", "faculty", "study_year", "registered_date", "kind"])
    for r in conn.execute("SELECT id,booth_id,faculty,study_year,registered_date,kind FROM donors_stats ORDER BY id"):
        w.writerow(list(r))
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="rejestracje.csv"'})
