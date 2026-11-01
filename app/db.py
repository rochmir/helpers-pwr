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
STUDENTS_SEED_PATH = Path(__file__).with_name("seed_students.json")
DEFAULT_FACEBOOK_URL = "https://www.facebook.com/samorzadpwr"

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
  won_genotype TEXT NULL, won_at TEXT NULL, won_token TEXT NULL,
  consent_at TEXT NULL, device_key TEXT NULL, device_ext_key TEXT NULL);
CREATE TABLE IF NOT EXISTS game_attempts(
  session_id TEXT, date TEXT, attempts INTEGER NOT NULL DEFAULT 0, best INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(session_id, date));
CREATE TABLE IF NOT EXISTS registration_codes(
  code TEXT PRIMARY KEY, booth_id TEXT NOT NULL REFERENCES booths(id),
  status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')),
  created_at TEXT NOT NULL, used_at TEXT NULL,
  kind TEXT NOT NULL DEFAULT 'potential' CHECK(kind IN ('potential','actual')));
CREATE TABLE IF NOT EXISTS donors_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, faculty TEXT NOT NULL, created_at TEXT NOT NULL, device_hash TEXT NULL);
-- Licznik zbiorczy faktycznych dawców per wydział (bez głosu, czasu i skrótu urządzenia): §3.4 Pucharu zabrania
-- trzymać typ dawcy w rekordzie głosu (donors_stats), a na /puchar pokazujemy podział LD na nowych i faktycznych.
CREATE TABLE IF NOT EXISTS cup_actual_counts(faculty TEXT PRIMARY KEY, actual INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS volunteers(
  login TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'volunteer' CHECK(role IN ('volunteer','admin')));
CREATE TABLE IF NOT EXISTS wins(
  token TEXT PRIMARY KEY, seq INTEGER NOT NULL, genotype TEXT NOT NULL, booth_id TEXT NOT NULL,
  won_at TEXT NOT NULL, session_id TEXT NULL, is_test INTEGER NOT NULL DEFAULT 0, submitted_at TEXT NULL);
CREATE TABLE IF NOT EXISTS booth_plays(
  device_key TEXT NOT NULL, booth_id TEXT NOT NULL, date TEXT NOT NULL, session_id TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, ext_key TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(device_key, booth_id, date, session_id));
CREATE TABLE IF NOT EXISTS promo_codes(
  code TEXT PRIMARY KEY, booth_id TEXT NOT NULL REFERENCES booths(id),
  status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')),
  created_at TEXT NOT NULL, used_at TEXT NULL);
CREATE TABLE IF NOT EXISTS partners(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, filename TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legal_documents(
  slug TEXT PRIMARY KEY, title TEXT NOT NULL, body_md TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legal_document_versions(
  slug TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL, body_md TEXT NOT NULL,
  saved_at TEXT NOT NULL, saved_by TEXT NOT NULL DEFAULT '', PRIMARY KEY(slug, version));
"""

CODE_TABLES = ("registration_codes", "promo_codes")
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
    _add_column(conn, "game_sessions", "pass_booth", "TEXT NULL")
    _add_column(conn, "game_sessions", "pass_until", "TEXT NULL")
    # dawca faktyczny (legitymacja) i terminy stanowisk
    _add_column(conn, "registration_codes", "kind", "TEXT NOT NULL DEFAULT 'potential' CHECK(kind IN ('potential','actual'))")
    _add_column(conn, "booths", "building", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "booths", "date_from", "TEXT NULL")
    _add_column(conn, "booths", "date_to", "TEXT NULL")
    # wzór i czas trafienia (anonimowo, bez nicku) + oznaczenie trafień testowych
    _add_column(conn, "genotype_history", "is_test", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "game_sessions", "won_genotype", "TEXT NULL")
    _add_column(conn, "game_sessions", "won_at", "TEXT NULL")
    # iteracja 4: tokeny trafień zamiast losowania, klucz urządzenia, role kont
    conn.execute("DROP TABLE IF EXISTS raffle_draws")
    _add_column(conn, "game_sessions", "won_token", "TEXT NULL")
    _add_column(conn, "game_sessions", "consent_at", "TEXT NULL")
    _add_column(conn, "game_sessions", "device_key", "TEXT NULL")
    _add_column(conn, "volunteers", "role", "TEXT NOT NULL DEFAULT 'volunteer' CHECK(role IN ('volunteer','admin'))")
    # iteracja 5: klucz rozszerzony urzadzenia
    _add_column(conn, "game_sessions", "device_ext_key", "TEXT NULL")
    _add_column(conn, "booth_plays", "ext_key", "TEXT NOT NULL DEFAULT ''")
    _migrate_cup_contest(conn)
    _backfill_wins(conn)
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


def _drop_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    if any(c["name"] == column for c in conn.execute(f"PRAGMA table_info({table})")):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def _migrate_cup_contest(conn: sqlite3.Connection) -> None:
    """Iteracja 7 (regulaminy Konkursu i Pucharu): minimalizacja danych, jeden głos z urządzenia, token jednorazowy.
    Idempotentna: każdy krok sprawdza, czy jest jeszcze potrzebny."""
    # Dodatkowe próby (kod promo +5, udział w Pucharze +10/+20) wróciły: promo_codes i bonus_attempts powstają
    # w SCHEMA i w kroku poniżej, a tu ich NIE kasujemy (migracja biegnie przy każdym starcie).
    conn.execute("CREATE TABLE IF NOT EXISTS promo_codes(code TEXT PRIMARY KEY, booth_id TEXT NOT NULL REFERENCES booths(id), "
                 "status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')), created_at TEXT NOT NULL, used_at TEXT NULL)")
    _add_column(conn, "game_sessions", "bonus_attempts", "INTEGER NOT NULL DEFAULT 0")
    # §3.4 Pucharu: bez numeru legitymacji (także jego skrótu)
    conn.execute("DROP TABLE IF EXISTS actual_donor_cards")
    _drop_column(conn, "registration_codes", "card_hash")
    # §3.4 Pucharu: donors_stats trzyma tylko wydział, znacznik czasu i skrót urządzenia
    cols = {c["name"] for c in conn.execute("PRAGMA table_info(donors_stats)")}
    if cols & {"study_year", "booth_id", "kind", "registered_date"} or "created_at" not in cols:
        conn.execute("DROP TABLE IF EXISTS donors_stats_new")
        conn.execute("CREATE TABLE donors_stats_new(id INTEGER PRIMARY KEY AUTOINCREMENT, faculty TEXT NOT NULL, "
                     "created_at TEXT NOT NULL, device_hash TEXT NULL)")
        if "registered_date" in cols:
            for r in conn.execute("SELECT id, faculty, registered_date FROM donors_stats ORDER BY id").fetchall():
                conn.execute("INSERT INTO donors_stats_new(id,faculty,created_at) VALUES(?,?,?)",
                             (r["id"], r["faculty"], config.noon_iso(r["registered_date"])))
        conn.execute("DROP TABLE donors_stats")
        conn.execute("ALTER TABLE donors_stats_new RENAME TO donors_stats")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_donors_device ON donors_stats(device_hash) "
                 "WHERE device_hash IS NOT NULL")
    # §4.3 Konkursu: wpis trafienia bez powiązania z sesją gracza; §6.2: jednorazowość tokenu
    _add_column(conn, "wins", "submitted_at", "TEXT NULL")
    conn.execute("UPDATE wins SET session_id=NULL WHERE session_id IS NOT NULL")


def _backfill_wins(conn: sqlite3.Connection) -> None:
    """Dopisuje wpis w ``wins`` do każdego dotychczasowego trafienia (wg ``matched_at``), raz na trafienie."""
    rows = conn.execute("SELECT genotype, booth_id, matched_at, is_test FROM genotype_history "
                        "WHERE matched_at IS NOT NULL AND genotype NOT IN (SELECT genotype FROM wins) "
                        "ORDER BY matched_at, genotype").fetchall()
    for r in rows:
        sess = conn.execute("SELECT session_id FROM game_sessions WHERE won_genotype=?", (r["genotype"],)).fetchone()
        sid = sess[0] if sess else None
        token = _insert_win(conn, r["genotype"], r["booth_id"], r["matched_at"], bool(r["is_test"]))
        if sid:
            conn.execute("UPDATE game_sessions SET won_token=? WHERE session_id=?", (token, sid))


def _insert_win(conn: sqlite3.Connection, genotype: str, booth_id: str, won_at: str, is_test: bool) -> str:
    """Wpis w ``wins`` z unikalnym tokenem HG-XXXX-XXXX i kolejnym numerem porządkowym (testowe: 0).
    Zapisujemy tylko token, czas, wzór i stoisko (§4.3 regulaminu), bez powiązania z sesją. Wołać w transakcji."""
    seq = 0
    if not is_test:
        seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM wins WHERE is_test=0").fetchone()[0]
    while True:
        token = "HG-" + "-".join("".join(secrets.choice(config.CODE_ALPHABET) for _ in range(4)) for _ in range(2))
        if conn.execute("SELECT 1 FROM wins WHERE token=?", (token,)).fetchone() is None:
            break
    conn.execute("INSERT INTO wins(token,seq,genotype,booth_id,won_at,is_test) VALUES(?,?,?,?,?,?)",
                 (token, seq, genotype, booth_id, won_at, int(is_test)))
    return token


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
        if conn.execute("SELECT 1 FROM settings WHERE key='faculty_students'").fetchone() is None:
            seed = json.loads(STUDENTS_SEED_PATH.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO settings(key,value) VALUES('faculty_students',?)",
                         (json.dumps({"source": seed.get("source", ""), "counts": seed.get("counts", {})},
                                     ensure_ascii=False),))
        # Domyślny profil Samorządu (miejsce zgłoszeń konkursowych); raz, żeby admin mógł go potem wyczyścić.
        if not get_setting(conn, "facebook_url") and not get_setting(conn, "facebook_url_seeded"):
            set_setting(conn, "facebook_url", DEFAULT_FACEBOOK_URL)
            set_setting(conn, "facebook_url_seeded", "1")
        from . import legal
        legal.seed(conn)
    finally:
        conn.close()
    bootstrap_booths()


def get_booth_hours(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key='booth_hours'").fetchone()
    return row[0] if row else ""


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))


def device_tolerance(conn: sqlite3.Connection) -> int:
    try:
        return min(50, max(1, int(get_setting(conn, "device_tolerance", str(config.DEVICE_TOLERANCE)))))
    except ValueError:
        return config.DEVICE_TOLERANCE


def get_students(conn: sqlite3.Connection) -> dict:
    """Liczby studentów wydziałów (LS) do Pucharu Dawcy PWr: ``{source, counts:{kod:int}}``."""
    try:
        d = json.loads(get_setting(conn, "faculty_students", "{}"))
    except ValueError:
        d = {}
    return {"source": d.get("source", ""), "counts": d.get("counts", {})}


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
               is_test: bool = False) -> tuple[str, str, str]:
    """Trafienie genotypu stoiska: licznik, nowy unikalny genotyp, matched_at starego i wpis w ``wins``.
    Z ``sid`` zapisuje wzór, czas i token tylko w sesji gracza (do odtworzenia jego certyfikatu), tym samym znacznikiem czasu.
    ``is_test`` oznacza trafienie z narzędzi testowych (seq 0). Wołać w transakcji; zwraca (stary, nowy, token)."""
    old = conn.execute("SELECT current_genotype FROM booths WHERE id=?", (booth_id,)).fetchone()[0]
    ts = config.now_iso()
    new = fresh_genotype(conn)
    conn.execute("UPDATE booths SET matches_count=matches_count+1, current_genotype=?, "
                 "genotype_updated_at=? WHERE id=?", (new, ts, booth_id))
    conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at) VALUES(?,?,?)", (new, booth_id, ts))
    conn.execute("UPDATE genotype_history SET matched_at=?, is_test=? WHERE genotype=?", (ts, int(is_test), old))
    token = _insert_win(conn, old, booth_id, ts, is_test)
    if sid is not None:
        conn.execute("UPDATE game_sessions SET won_genotype=?, won_at=?, won_token=? WHERE session_id=?",
                     (old, ts, token, sid))
    return old, new, token


def device_salt(conn: sqlite3.Connection) -> str:
    """Sól dobowa klucza urządzenia (Europe/Warsaw). Pierwsze użycie nowego dnia losuje nową sól, kasuje stare
    ``booth_plays`` i zeruje ``game_sessions.device_key`` i ``device_ext_key``, więc klucza nie da się powiązać między dniami."""
    today = config.today()
    d = json.loads(get_setting(conn, "device_salt", "{}"))
    if d.get("date") == today:
        return d["salt"]
    with tx(conn):
        d = json.loads(get_setting(conn, "device_salt", "{}"))  # ponowny odczyt pod blokadą zapisu
        if d.get("date") != today:
            d = {"date": today, "salt": secrets.token_hex(32)}
            set_setting(conn, "device_salt", json.dumps(d))
            conn.execute("DELETE FROM booth_plays WHERE date<?", (today,))
            conn.execute("UPDATE game_sessions SET device_key=NULL, device_ext_key=NULL")
    return d["salt"]


def rotate_device_salt() -> None:
    """Rotacja soli bez ruchu na stronie (zadanie w tle co godzinę)."""
    conn = connect()
    try:
        device_salt(conn)
    finally:
        conn.close()


def expire_codes(conn: sqlite3.Connection) -> None:
    """Leniwe wygaszanie kodów po CODE_TTL_MINUTES."""
    from datetime import timedelta
    cutoff = config.iso(config.now() - timedelta(minutes=config.code_ttl_minutes()))
    for table in CODE_TABLES:
        conn.execute(f"UPDATE {table} SET status='EXPIRED' WHERE status='ACTIVE' AND created_at < ?", (cutoff,))


def unique_code(conn: sqlite3.Connection, booth_id: str) -> str | None:
    """Nowy kod ``STOISKO-XXXX`` unikalny w obu tabelach kodów (None po 20 nieudanych próbach). Wołać w transakcji."""
    for _ in range(20):
        code = f"{booth_id.upper()}-" + "".join(secrets.choice(config.CODE_ALPHABET) for _ in range(4))
        if not any(conn.execute(f"SELECT 1 FROM {t} WHERE code=?", (code,)).fetchone() for t in CODE_TABLES):
            return code
    return None


def list_codes(conn: sqlite3.Connection, booth_id: str | None = None, status: str | None = None,
               limit: int = 20) -> list[sqlite3.Row]:
    """Tokeny rejestracyjne i kody dodatkowych prób razem (te drugie z ``kind='promo'``), najnowsze pierwsze."""
    where, args = [], []
    if booth_id:
        where.append("booth_id=?"); args.append(booth_id)
    if status:
        where.append("status=?"); args.append(status)
    w = " WHERE " + " AND ".join(where) if where else ""
    sql = (f"SELECT code,booth_id,status,created_at,used_at,kind,rowid AS seq FROM registration_codes{w} UNION ALL "
           f"SELECT code,booth_id,status,created_at,used_at,'promo',rowid FROM promo_codes{w} "
           "ORDER BY created_at DESC, seq DESC LIMIT ?")
    return conn.execute(sql, args * 2 + [limit]).fetchall()


def find_code(conn: sqlite3.Connection, code: str) -> tuple[str, sqlite3.Row] | None:
    """(tabela, wiersz) tokenu rejestracyjnego albo kodu dodatkowych prób."""
    for table in CODE_TABLES:
        row = conn.execute(f"SELECT * FROM {table} WHERE code=?", (code,)).fetchone()
        if row is not None:
            return table, row
    return None


def used_counts(conn: sqlite3.Connection, booth_id: str | None = None, date: str | None = None) -> dict[str, int]:
    """Zużyte tokeny wg typu (``potential`` / ``actual``): źródło zestawień per stoisko i typ, bo ``donors_stats``
    nie trzyma stoiska ani typu (§3.4 regulaminu Pucharu). ``date`` = doba Europe/Warsaw."""
    where, args = ["status='USED'"], []
    if booth_id:
        where.append("booth_id=?"); args.append(booth_id)
    if date:
        start, end = config.day_bounds(date)
        where.append("used_at>=? AND used_at<?"); args += [start, end]
    rows = conn.execute(f"SELECT kind, COUNT(*) n FROM registration_codes WHERE {' AND '.join(where)} GROUP BY kind", args)
    return {r["kind"]: r["n"] for r in rows}


def device_stats(conn: sqlite3.Connection) -> dict:
    """Liczby różnych kluczy urządzeń dziś w ``booth_plays`` (do oceny kolizji na prawdziwych telefonach)."""
    today = config.today()
    r = conn.execute("SELECT COUNT(DISTINCT device_key), COUNT(DISTINCT CASE WHEN ext_key<>'' THEN ext_key END) "
                     "FROM booth_plays WHERE date=?", (today,)).fetchone()
    return {"date": today, "base_keys": r[0], "ext_keys": r[1]}
