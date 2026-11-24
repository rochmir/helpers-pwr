"""Panel admina: stoiska, konta, słownik, ustawienia, liczby studentów, trafienia i weryfikacja Tokenu Losu, podsumowania, eksport CSV."""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import auth, config, db
from . import stats

router = APIRouter(prefix="/api/admin")
BOOTH_ID_RE = re.compile(r"^[a-z0-9]{1,20}$")
LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FACULTY_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
PASSWORD_MIN = 8
# Alfabet bez znaków łatwych do pomylenia (0/O/1/l/I).
PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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
    role: str = Field("volunteer", max_length=16)


class RoleIn(BaseModel):
    role: str = Field(max_length=16)


class SettingsIn(BaseModel):
    cup_deadline: str | None = Field(None, max_length=40)
    contest_deadline: str | None = Field(None, max_length=40)
    facebook_url: str = Field("", max_length=300)


class StudentsIn(BaseModel):
    source: str = Field("", max_length=500)
    counts: dict[str, int | None] = Field(max_length=100)


class PasswordIn(BaseModel):
    password: str | None = Field(None, max_length=256)


class Faculty(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=200)


class DictionaryIn(BaseModel):
    faculties: list[Faculty] = Field(max_length=100)


# --- stoiska --------------------------------------------------------------------
@router.get("/booths")
def list_booths(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM donors_stats d WHERE d.booth_id=b.id) AS registered "
        "FROM booths b ORDER BY b.id")
    return [{k: r[k] for k in ("id", "name", "current_genotype", "genotype_updated_at", "matches_count",
                               "rolls_count", "registered", "building", "date_from", "date_to")}
            | {"is_lecture": bool(r["is_lecture"]), "has_screen": bool(r["screen_token"])} for r in rows]


@router.post("/booths", status_code=201)
def create_booth(body: BoothIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    bid, name = body.id.strip().lower(), body.name.strip()
    if not BOOTH_ID_RE.match(bid):
        raise HTTPException(422, "Id stoiska: 1-20 znaków, małe litery i cyfry.")
    if not name:
        raise HTTPException(422, "Nazwa stoiska nie może być pusta.")
    if bid in db.RESERVED_BOOTH_IDS:
        raise HTTPException(422, "Ten identyfikator jest zarezerwowany.")
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
        booth = conn.execute("SELECT is_lecture FROM booths WHERE id=?", (booth_id,)).fetchone()
        if booth is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        if booth["is_lecture"]:
            raise HTTPException(409, "Stanowiska Zajęcia nie można usunąć.")
        used = conn.execute("SELECT (SELECT COUNT(*) FROM donors_stats WHERE booth_id=?) + "
                            "(SELECT COUNT(*) FROM registration_codes WHERE booth_id=?) + "
                            "(SELECT COUNT(*) FROM promo_codes WHERE booth_id=?)", (booth_id, booth_id, booth_id)).fetchone()[0]
        if used:
            raise HTTPException(409, "Stoisko ma zapisane głosy w Pucharze, więc nie można go usunąć.")
        conn.execute("DELETE FROM genotype_history WHERE booth_id=?", (booth_id,))
        conn.execute("DELETE FROM cup_qr_codes WHERE booth_id=?", (booth_id,))
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


def _screen_view(token: str | None) -> dict:
    return {"url": f"{config.public_url()}/ekran/{token}" if token else None}


@router.get("/booths/{booth_id}/screen")
def get_booth_screen(booth_id: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Stały link do ekranu stoiska (albo null, gdy ekran wyłączony)."""
    row = conn.execute("SELECT screen_token FROM booths WHERE id=?", (booth_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Nie ma takiego stoiska.")
    return _screen_view(row["screen_token"])


@router.post("/booths/{booth_id}/screen")
def rotate_booth_screen(booth_id: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Tworzy albo rotuje link do ekranu stoiska; poprzedni przestaje działać."""
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM booths WHERE id=?", (booth_id,)).fetchone() is None:
            raise HTTPException(404, "Nie ma takiego stoiska.")
        # Zajęcia dostają łatwy do zapamiętania kod (wolontariusz wpisuje go ręcznie), reszta losowy token.
        token = db.new_lecture_screen_code() if booth_id == db.LECTURE_BOOTH_ID else secrets.token_urlsafe(16)
        conn.execute("UPDATE booths SET screen_token=? WHERE id=?", (token, booth_id))
    return _screen_view(token)


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


def _check_role(role: str) -> None:
    if role not in ("volunteer", "admin"):
        raise HTTPException(422, "Ranga konta: wolontariusz albo admin.")


@router.get("/volunteers")
def list_volunteers(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return [{"login": r["login"], "role": r["role"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT login, role, created_at FROM volunteers ORDER BY login")]


@router.post("/volunteers", status_code=201)
def create_volunteer(body: VolunteerIn, _: dict = Depends(auth.require_admin),
                     conn: sqlite3.Connection = Depends(db.get_db)):
    login = body.login.strip().lower()
    if not LOGIN_RE.match(login):
        raise HTTPException(422, "Login: 3-32 znaków, małe litery, cyfry oraz . _ -")
    if login == auth.ADMIN_LOGIN:
        raise HTTPException(422, "Login „admin” jest zarezerwowany.")
    _check_role(body.role)
    password = _password(body.password)
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM volunteers WHERE login=?", (login,)).fetchone():
            raise HTTPException(409, "Konto o tym loginie już istnieje.")
        conn.execute("INSERT INTO volunteers(login,password_hash,created_at,role) VALUES(?,?,?,?)",
                     (login, db.hasher.hash(password), config.now_iso(), body.role))
    return {"login": login, "role": body.role, "password": password}  # jedyny moment, w którym hasło jest widoczne


@router.patch("/volunteers/{login}")
def set_volunteer_role(login: str, body: RoleIn, _: dict = Depends(auth.require_admin),
                       conn: sqlite3.Connection = Depends(db.get_db)):
    _check_role(body.role)
    login = login.strip().lower()
    with db.tx(conn):
        if conn.execute("UPDATE volunteers SET role=? WHERE login=?", (body.role, login)).rowcount == 0:
            raise HTTPException(404, "Nie ma takiego konta.")
    return {"login": login, "role": body.role}


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
            raise HTTPException(409, "Nie można usunąć wydziałów, które mają punkty: " + ", ".join(missing) + ".")
        old = db.get_dictionary(conn)
        # „Inne” zawsze na końcu (nie da się go zgubić ani przesunąć).
        db.set_dictionary(conn, {"_note": old.get("_note", ""), "faculties": db.with_other_last(faculties)})
    return {"ok": True}


# --- trafienia 10/10 i weryfikacja Tokenu Losu ----------------------------------
def normalize_token(raw: str) -> str:
    """Wielkie litery, bez spacji, różne myślniki jak „-”; HGXXXXXXXX dostaje myślniki HG-XXXX-XXXX."""
    t = re.sub(r"\s+", "", re.sub(r"[\u2010-\u2015\u2212]", "-", raw or "")).upper()
    m = re.fullmatch(r"HG-?([A-Z0-9]{4})-?([A-Z0-9]{4})", t)
    return f"HG-{m.group(1)}-{m.group(2)}" if m else t


def _win(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    """Prawdziwe trafienie o danym tokenie (testowe traktujemy jak nieistniejące)."""
    return conn.execute("SELECT w.token, w.genotype, w.won_at, w.submitted_at, b.name AS booth_name FROM wins w "
                        "LEFT JOIN booths b ON b.id=w.booth_id WHERE w.token=? AND w.is_test=0",
                        (normalize_token(token),)).fetchone()


@router.get("/wins")
def list_wins(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT w.seq, w.token, w.genotype, w.booth_id, b.name AS booth_name, w.won_at, w.submitted_at "
                        "FROM wins w LEFT JOIN booths b ON b.id=w.booth_id WHERE w.is_test=0 ORDER BY w.seq")
    wins = [dict(r) for r in rows]
    return {"count": len(wins), "wins": wins}


@router.get("/tokens/{token}")
def check_token(token: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Warunki §6.2 regulaminu Konkursu: token istnieje, ma wzór i datę z rejestru, nie był wykorzystany."""
    w = _win(conn, token)
    if w is None:
        return {"exists": False, "token": normalize_token(token), "genotype": None, "won_at": None,
                "booth_name": None, "submitted_at": None}
    return {"exists": True, "token": w["token"], "genotype": w["genotype"], "won_at": w["won_at"],
            "booth_name": w["booth_name"], "submitted_at": w["submitted_at"]}


@router.post("/tokens/{token}/submit")
def submit_token(token: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Oznacza token jako wykorzystany w zgłoszeniu (atomowo: drugi raz = 409)."""
    t = normalize_token(token)
    with db.tx(conn):
        if _win(conn, t) is None:
            raise HTTPException(404, "Nie ma takiego tokenu w rejestrze wygranych 10/10.")
        ts = config.now_iso()
        if conn.execute("UPDATE wins SET submitted_at=? WHERE token=? AND is_test=0 AND submitted_at IS NULL",
                        (ts, t)).rowcount == 0:
            raise HTTPException(409, "Ten token został już wykorzystany we wcześniejszym zgłoszeniu.")
    return {"ok": True, "token": t, "submitted_at": ts}


@router.post("/tokens/{token}/unsubmit")
def unsubmit_token(token: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Cofnięcie pomyłkowego oznaczenia tokenu jako wykorzystanego."""
    t = normalize_token(token)
    with db.tx(conn):
        if _win(conn, t) is None:
            raise HTTPException(404, "Nie ma takiego tokenu w rejestrze wygranych 10/10.")
        if conn.execute("UPDATE wins SET submitted_at=NULL WHERE token=? AND is_test=0 AND submitted_at IS NOT NULL",
                        (t,)).rowcount == 0:
            raise HTTPException(409, "Ten token nie jest oznaczony jako wykorzystany.")
    return {"ok": True, "token": t}


# --- ustawienia i liczby studentów ----------------------------------------------
def _local_minute(dt) -> str:
    return dt.astimezone(config.TZ).strftime("%Y-%m-%dT%H:%M")


def _deadline_view(conn: sqlite3.Connection, key: str, effective, default) -> dict:
    """Termin do panelu: obowiązujący (czas Warsaw, do ``datetime-local``), domyślny z env/kodu i czy jest nadpisany."""
    return {"value": _local_minute(effective), "default": _local_minute(default),
            "custom": bool(db.get_setting(conn, key))}


def _settings_view(conn: sqlite3.Connection) -> dict:
    return {"facebook_url": db.get_setting(conn, "facebook_url"),
            "cup_deadline": _deadline_view(conn, "cup_deadline", config.cup_deadline(),
                                           config.env_deadline("CUP_DEADLINE", config.DEFAULT_CUP_DEADLINE)),
            "contest_deadline": _deadline_view(conn, "contest_deadline", config.contest_deadline(),
                                               config.env_deadline("CONTEST_DEADLINE", config.DEFAULT_CONTEST_DEADLINE))}


@router.get("/settings")
def get_settings(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return _settings_view(conn)


def _normalize_deadline(raw: str | None, label: str) -> str:
    """Pusty = powrót do wartości domyślnej (env); inaczej poprawna data i godzina, zapis w czasie Warsaw z dokładnością do minuty."""
    if raw is None or not raw.strip():
        return ""
    dt = config.parse_deadline(raw)
    if dt is None:
        raise HTTPException(422, f"{label}: niepoprawna data i godzina.")
    return _local_minute(dt)


@router.put("/settings")
def put_settings(body: SettingsIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    url = body.facebook_url.strip()
    if url and (not url.startswith("https://") or len(url) <= 8 or any(c.isspace() for c in url)):
        raise HTTPException(422, "Link do Facebooka musi zaczynać się od https://.")
    cup = _normalize_deadline(body.cup_deadline, "Koniec zliczania punktów Pucharu")
    contest = _normalize_deadline(body.contest_deadline, "Koniec przyjmowania zgłoszeń do konkursu")
    with db.tx(conn):
        db.set_setting(conn, "facebook_url", url)
        # pole pominięte (None) też resetuje do domyślnego: panel zawsze wysyła oba pola
        db.set_setting(conn, "cup_deadline", cup)
        db.set_setting(conn, "contest_deadline", contest)
    return _settings_view(conn)


@router.get("/students")
def get_students(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    return db.get_students(conn)


@router.put("/students")
def put_students(body: StudentsIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    known = {f["code"] for f in db.get_dictionary(conn)["faculties"]}
    counts = {}
    for code, n in body.counts.items():
        if code not in known:
            raise HTTPException(422, f"Nieznany wydział: {code}.")
        if n is None:
            continue
        if not 1 <= n <= 100000:
            raise HTTPException(422, f"Liczba studentów wydziału {code}: od 1 do 100000.")
        counts[code] = n
    out = {"source": body.source.strip(), "counts": counts}
    db.set_setting(conn, "faculty_students", json.dumps(out, ensure_ascii=False))
    return out


# --- głosy w Pucharze -----------------------------------------------------------
@router.delete("/votes/{vote_id}")
def delete_vote(vote_id: int, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Usuwa pomyłkowy głos z Pucharu (wiersz donors_stats)."""
    with db.tx(conn):
        if conn.execute("DELETE FROM donors_stats WHERE id=?", (vote_id,)).rowcount == 0:
            raise HTTPException(404, "Nie ma takiego głosu.")
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
        start, end = config.day_bounds(d)
        registered = conn.execute("SELECT COUNT(*) FROM donors_stats WHERE created_at>=? AND created_at<?",
                                  (start, end)).fetchone()[0]
        g = conn.execute("SELECT COUNT(*) p, COALESCE(SUM(attempts),0) r FROM game_attempts WHERE date=?", (d,)).fetchone()
        players, rolls = g["p"], g["r"]
        matches = sum(1 for r in conn.execute("SELECT matched_at FROM genotype_history WHERE matched_at IS NOT NULL")
                      if config.warsaw_date(r["matched_at"]) == d)
    podium = [f for f in stats.faculty_counts(conn, d) if f["count"] > 0][:3]
    return {"scope": "all" if d is None else "day", "date": date, "registered": registered,
            "registered_total": total, "podium": podium,
            "cup": [r for r in stats.cup(conn, d)["ranking"] if r["qualified"]][:3],  # próg LD jak w /api/stats/cup
            "game": {"players": players, "rolls": rolls, "matches": matches}}


@router.get("/days")
def days(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    found = {config.warsaw_date(r[0]) for r in conn.execute("SELECT created_at FROM donors_stats")}
    found |= {r[0] for r in conn.execute("SELECT date FROM game_attempts")}
    found |= {config.warsaw_date(r[0]) for r in conn.execute(
        "SELECT matched_at FROM genotype_history WHERE matched_at IS NOT NULL")}
    return sorted(found, reverse=True)


def _csv(rows: list[list], header: list[str], filename: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export-csv")
def export_csv(set: str = "punkty", _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """``punkty``: głosy w Pucharze (id, wydział, kategoria, status, stoisko, data i godzina UTC). ``stoiska``:
    liczba głosów wg stoiska, kategorii i doby (zestawienie do audytu §6.3 regulaminu Pucharu).
    ``zestawienie``: liczba głosów wg wydziału, kategorii i statusu (długi format; nieznany kod statusu = sam kod)."""
    if set == "zestawienie":
        names = {f["code"]: f["name"] for f in db.get_dictionary(conn)["faculties"]}
        labels = dict(config.STUDY_YEARS)
        rows = conn.execute("SELECT faculty, category, study_year, COUNT(*) n FROM donors_stats "
                            "GROUP BY faculty, category, study_year ORDER BY faculty, category, study_year").fetchall()
        return _csv([[r["faculty"], names.get(r["faculty"], r["faculty"]), r["category"], r["study_year"],
                      labels.get(r["study_year"], r["study_year"]), r["n"]] for r in rows],
                    ["faculty", "faculty_name", "category", "study_year", "status_label", "count"], "puchar-zestawienie.csv")
    if set == "stoiska":
        counts: dict[tuple[str, str, str], int] = {}
        for r in conn.execute("SELECT booth_id, category, created_at FROM donors_stats"):
            key = (r["booth_id"] or "", r["category"], config.warsaw_date(r["created_at"]))
            counts[key] = counts.get(key, 0) + 1
        return _csv([[*k, n] for k, n in sorted(counts.items())], ["booth_id", "category", "date", "count"],
                    "glosy-wg-stoisk.csv")
    return _csv([list(r) for r in conn.execute(
        "SELECT id,faculty,category,study_year,booth_id,created_at FROM donors_stats ORDER BY id")],
        ["id", "faculty", "category", "study_year", "booth_id", "created_at"], "punkty.csv")
