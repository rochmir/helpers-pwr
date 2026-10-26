"""SQLite: połączenie na żądanie, schemat, seed słownika, pomocnicze zapytania."""
from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from argon2 import PasswordHasher

from . import config, game

log = logging.getLogger("helpersi.db")
hasher = PasswordHasher()

SEED_PATH = Path(__file__).with_name("seed_dictionary.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS booths(
  id TEXT PRIMARY KEY CHECK(id GLOB '[a-z0-9]*'),
  name TEXT NOT NULL, pin_hash TEXT NOT NULL,
  current_genotype TEXT NOT NULL, genotype_updated_at TEXT NOT NULL,
  matches_count INTEGER NOT NULL DEFAULT 0, rolls_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  building TEXT NOT NULL DEFAULT '', date_from TEXT NULL, date_to TEXT NULL);
CREATE TABLE IF NOT EXISTS genotype_history(
  genotype TEXT PRIMARY KEY, booth_id TEXT NOT NULL, created_at TEXT NOT NULL, matched_at TEXT NULL,
  is_test INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS game_sessions(
  session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, has_won INTEGER NOT NULL DEFAULT 0,
  bonus_attempts INTEGER NOT NULL DEFAULT 0, pass_booth TEXT NULL, pass_until TEXT NULL,
  won_genotype TEXT NULL, won_at TEXT NULL);
CREATE TABLE IF NOT EXISTS game_attempts(
  session_id TEXT, date TEXT, attempts INTEGER NOT NULL DEFAULT 0, best INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(session_id, date));
CREATE TABLE IF NOT EXISTS registration_codes(
  code TEXT PRIMARY KEY, booth_id TEXT NOT NULL REFERENCES booths(id),
  status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')),
  created_at TEXT NOT NULL, used_at TEXT NULL,
  kind TEXT NOT NULL DEFAULT 'potential' CHECK(kind IN ('potential','actual')), card_hash TEXT NULL);
CREATE TABLE IF NOT EXISTS donors_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, booth_id TEXT NOT NULL REFERENCES booths(id),
  faculty TEXT NOT NULL, study_year INTEGER NOT NULL,
  registered_date TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'potential');
CREATE TABLE IF NOT EXISTS actual_donor_cards(
  card_hash TEXT PRIMARY KEY, registered_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS volunteers(
  login TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raffle_draws(
  id INTEGER PRIMARY KEY AUTOINCREMENT, genotype TEXT NOT NULL REFERENCES genotype_history(genotype),
  drawn_at TEXT NOT NULL);
"""

OTHER_FACULTY = {"code": "INNE", "name": "Inne"}


def connect() -> sqlite3.Connection:
    # Autocommit; transakcje zapisu jawnie przez tx().
    conn = sqlite3.connect(config.db_path(), isolation_level=None, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    """Zależność FastAPI: świeże połączenie na żądanie."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection):
    """Transakcja zapisu (BEGIN IMMEDIATE); wyjątek = ROLLBACK."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def study_years() -> list[dict]:
    return _seed()["study_years"]


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not any(c["name"] == column for c in conn.execute(f"PRAGMA table_info({table})")):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def with_other_last(faculties: list[dict]) -> list[dict]:
    """Wydział „Inne” zawsze na końcu listy (dopisany, jeśli go brak)."""
    rest = [f for f in faculties if f["code"] != OTHER_FACULTY["code"]]
    other = next((f for f in faculties if f["code"] == OTHER_FACULTY["code"]), dict(OTHER_FACULTY))
    return rest + [other]


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotentne migracje schematu i słownika (baza produkcyjna już istnieje, dane zostają)."""
    # iteracja 2: bez kierunków studiów
    if any(c["name"] == "major" for c in conn.execute("PRAGMA table_info(donors_stats)")):
        conn.execute("ALTER TABLE donors_stats DROP COLUMN major")
    # iteracja 3: najlepszy wynik dnia, bonus za rejestrację, przepustka stoiska
    _add_column(conn, "game_attempts", "best", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "game_sessions", "bonus_attempts", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "game_sessions", "pass_booth", "TEXT NULL")
    _add_column(conn, "game_sessions", "pass_until", "TEXT NULL")
    # dawca faktyczny (legitymacja) i terminy stanowisk
    _add_column(conn, "registration_codes", "kind", "TEXT NOT NULL DEFAULT 'potential' CHECK(kind IN ('potential','actual'))")
    _add_column(conn, "registration_codes", "card_hash", "TEXT NULL")
    _add_column(conn, "donors_stats", "kind", "TEXT NOT NULL DEFAULT 'potential'")
    _add_column(conn, "booths", "building", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "booths", "date_from", "TEXT NULL")
    _add_column(conn, "booths", "date_to", "TEXT NULL")
    # losowanie finałowe: wzór i czas trafienia (anonimowo, bez nicku) + oznaczenie trafień testowych
    _add_column(conn, "genotype_history", "is_test", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "game_sessions", "won_genotype", "TEXT NULL")
    _add_column(conn, "game_sessions", "won_at", "TEXT NULL")
    row = conn.execute("SELECT value FROM settings WHERE key='dictionary'").fetchone()
    if row:
        d = json.loads(row["value"])
        for f in d.get("faculties", []):
            f.pop("majors", None)
        faculties = d.get("faculties", [])
        if faculties and faculties[-1].get("code") != OTHER_FACULTY["code"]:
            d["faculties"] = with_other_last(faculties)
        value = json.dumps(d, ensure_ascii=False)
        if value != row["value"]:
            conn.execute("UPDATE settings SET value=? WHERE key='dictionary'", (value,))


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        if conn.execute("SELECT 1 FROM settings WHERE key='dictionary'").fetchone() is None:
            seed = _seed()
            dictionary = {"_note": seed.get("_note", ""), "faculties": seed["faculties"]}
            conn.execute("INSERT INTO settings(key,value) VALUES('dictionary',?)",
                         (json.dumps(dictionary, ensure_ascii=False),))
    finally:
        conn.close()
    bootstrap_booths()


def get_booth_hours(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key='booth_hours'").fetchone()
    return row[0] if row else ""


def get_dictionary(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key='dictionary'").fetchone()
    return json.loads(row["value"]) if row else {"faculties": []}


def set_dictionary(conn: sqlite3.Connection, dictionary: dict) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES('dictionary',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (json.dumps(dictionary, ensure_ascii=False),))


# --- stoiska --------------------------------------------------------------------
def genotype_taken(conn: sqlite3.Connection):
    return lambda g: conn.execute("SELECT 1 FROM genotype_history WHERE genotype=?", (g,)).fetchone() is not None


def fresh_genotype(conn: sqlite3.Connection) -> str:
    """Nowy genotyp unikalny względem historii (zapis do historii robi wołający)."""
    return game.new_genotype(genotype_taken(conn))


def create_booth(conn: sqlite3.Connection, booth_id: str, name: str, building: str = "",
                 date_from: str | None = None, date_to: str | None = None) -> None:
    """Wstawia stoisko wraz z pierwszym genotypem. Wołać w transakcji.

    Kolumna ``pin_hash`` została po starym logowaniu PIN-em (NOT NULL); wpisujemy hash losowego sekretu."""
    ts = config.now_iso()
    g = fresh_genotype(conn)
    conn.execute("INSERT INTO booths(id,name,pin_hash,current_genotype,genotype_updated_at,created_at,"
                 "building,date_from,date_to) VALUES(?,?,?,?,?,?,?,?,?)",
                 (booth_id, name, hasher.hash(secrets.token_urlsafe(24)), g, ts, ts, building, date_from, date_to))
    conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at) VALUES(?,?,?)", (g, booth_id, ts))


def bootstrap_booths() -> None:
    """``BOOTSTRAP_BOOTHS="c13:Budynek C-13,w4:Budynek W-4"`` tworzy brakujące stoiska.

    Stary format ``id:nazwa:pin`` też działa (PIN jest ignorowany)."""
    raw = os.environ.get("BOOTSTRAP_BOOTHS", "").strip()
    if not raw:
        return
    conn = connect()
    try:
        for item in raw.split(","):
            parts = item.strip().split(":")
            if len(parts) < 2:
                log.warning("BOOTSTRAP_BOOTHS: pominięto niepoprawny wpis %r", item)
                continue
            if len(parts) >= 3 and parts[-1].strip().isdigit():  # stary format z PIN-em
                parts = parts[:-1]
            booth_id, name = parts[0].strip().lower(), ":".join(parts[1:]).strip()
            if not booth_id.isalnum() or not booth_id.isascii() or not name:
                log.warning("BOOTSTRAP_BOOTHS: pominięto niepoprawny wpis %r", booth_id)
                continue
            with tx(conn):
                if conn.execute("SELECT 1 FROM booths WHERE id=?", (booth_id,)).fetchone() is None:
                    create_booth(conn, booth_id, name)
                    log.info("Utworzono stoisko %s", booth_id)
    finally:
        conn.close()


def record_win(conn: sqlite3.Connection, booth_id: str, sid: str | None = None,
               is_test: bool = False) -> tuple[str, str]:
    """Trafienie genotypu stoiska: licznik, nowy unikalny genotyp, matched_at starego.
    Z ``sid`` zapisuje wzór i czas także w sesji gracza (do certyfikatu), tym samym znacznikiem czasu.
    ``is_test`` wyklucza trafienie z losowania finałowego. Wołać w transakcji; zwraca (stary, nowy)."""
    old = conn.execute("SELECT current_genotype FROM booths WHERE id=?", (booth_id,)).fetchone()[0]
    ts = config.now_iso()
    new = fresh_genotype(conn)
    conn.execute("UPDATE booths SET matches_count=matches_count+1, current_genotype=?, "
                 "genotype_updated_at=? WHERE id=?", (new, ts, booth_id))
    conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at) VALUES(?,?,?)", (new, booth_id, ts))
    conn.execute("UPDATE genotype_history SET matched_at=?, is_test=? WHERE genotype=?", (ts, int(is_test), old))
    if sid is not None:
        conn.execute("UPDATE game_sessions SET won_genotype=?, won_at=? WHERE session_id=?", (old, ts, sid))
    return old, new


def expire_codes(conn: sqlite3.Connection) -> None:
    """Leniwe wygaszanie kodów po CODE_TTL_MINUTES."""
    from datetime import timedelta
    cutoff = config.iso(config.now() - timedelta(minutes=config.code_ttl_minutes()))
    conn.execute("UPDATE registration_codes SET status='EXPIRED' WHERE status='ACTIVE' AND created_at < ?", (cutoff,))
