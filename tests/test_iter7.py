"""Iteracja 7: regulaminy Konkursu i Pucharu (limit na urządzenie, bez bonusów, Token Losu jednorazowy, jeden głos,
terminy, WZ) oraz dokumenty prawne edytowane z panelu. Migracja ze schematu iteracji 6."""
import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import config, db, game, legal
from test_api import JSON, enter, make_code, new_session, register, volunteer

LEGAL_DIR = Path(legal.__file__).parent / "legal"
OLD_SCHEMA = """
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
  kind TEXT NOT NULL DEFAULT 'potential' CHECK(kind IN ('potential','actual')), card_hash TEXT NULL);
CREATE TABLE IF NOT EXISTS donors_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, booth_id TEXT NOT NULL REFERENCES booths(id),
  faculty TEXT NOT NULL, study_year INTEGER NOT NULL,
  registered_date TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'potential');
CREATE TABLE IF NOT EXISTS actual_donor_cards(
  card_hash TEXT PRIMARY KEY, registered_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS volunteers(
  login TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'volunteer' CHECK(role IN ('volunteer','admin')));
CREATE TABLE IF NOT EXISTS wins(
  token TEXT PRIMARY KEY, seq INTEGER NOT NULL, genotype TEXT NOT NULL, booth_id TEXT NOT NULL,
  won_at TEXT NOT NULL, session_id TEXT NULL, is_test INTEGER NOT NULL DEFAULT 0);
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
"""


def roll(c, booth):
    return c.post("/api/game/roll", json={"booth_id": booth})


def always_win(monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)


def set_clock(monkeypatch, dt):
    monkeypatch.setattr(config, "now", lambda: dt)


def real_win(c, booth, monkeypatch):
    """Prawdziwe trafienie 10/10 w sesji ``c``; zwraca token."""
    always_win(monkeypatch)
    new_session(c, booth)
    return roll(c, booth).json()["won_token"]


# --- brak dodatkowych prób ------------------------------------------------------
def test_promo_mechanics_removed(admin, booth, client, conn):
    assert client.post("/api/donor/redeem-promo", json={"code": "C13-AAAA"}).status_code == 404
    assert admin.post("/api/volunteer/generate-code", json={"booth_id": booth, "kind": "promo"}).status_code == 422
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='promo_codes'").fetchone() is None
    for name in ("REGISTER_BONUS", "REGISTER_BONUS_ACTUAL", "PROMO_BONUS"):
        assert not hasattr(config, name)
    assert config.DAILY_ATTEMPTS == 5
    s = new_session(client, booth)
    assert set(s) == {"token", "attempts_left", "has_won", "best_today", "pass_booth", "won_genotype", "won_at",
                      "won_token", "won_seq", "won_booth_name"}


# --- Token Losu: weryfikacja i jednorazowość (§6.2) -----------------------------
def test_token_lookup_normalization_and_fields(admin, booth, other_clients, monkeypatch, conn):
    token = real_win(other_clients(), booth, monkeypatch)
    messy = "  " + token.lower().replace("-", " - ") + " "
    for raw in (token, messy, token.replace("-", "").lower()):
        d = admin.get("/api/admin/tokens/" + raw.replace(" ", "%20")).json()
        assert d["exists"] is True and d["token"] == token and d["booth_name"] == "Budynek C-13"
        assert re.fullmatch(r"[0-3]{10}", d["genotype"]) and d["won_at"].endswith("Z") and d["submitted_at"] is None
    row = conn.execute("SELECT genotype, won_at FROM wins WHERE token=?", (token,)).fetchone()
    assert (d["genotype"], d["won_at"]) == (row["genotype"], row["won_at"])
    nope = admin.get("/api/admin/tokens/HG-ZZZZ-ZZZZ").json()
    assert nope["exists"] is False and nope["genotype"] is None and nope["submitted_at"] is None


def test_token_submit_once_unsubmit(admin, booth, other_clients, monkeypatch):
    token = real_win(other_clients(), booth, monkeypatch)
    url = f"/api/admin/tokens/{token}"
    r = admin.post(url + "/submit", json={})
    assert r.status_code == 200 and r.json()["token"] == token and r.json()["submitted_at"].endswith("Z")
    assert admin.get(url).json()["submitted_at"] == r.json()["submitted_at"]
    r2 = admin.post(url.lower() + "/submit", json={})
    assert r2.status_code == 409 and "wykorzystany" in r2.json()["detail"]
    assert admin.get(url).json()["submitted_at"] == r.json()["submitted_at"]  # drugi raz niczego nie nadpisał
    assert admin.get("/api/admin/wins").json()["wins"][0]["submitted_at"] == r.json()["submitted_at"]
    assert admin.post(url + "/unsubmit", json={}).json() == {"ok": True, "token": token}
    assert admin.post(url + "/unsubmit", json={}).status_code == 409  # nie był oznaczony
    assert admin.get(url).json()["submitted_at"] is None
    assert admin.post(url + "/submit", json={}).status_code == 200  # po cofnięciu można znów
    assert admin.post("/api/admin/tokens/HG-ZZZZ-ZZZZ/submit", json={}).status_code == 404
    assert admin.post("/api/admin/tokens/HG-ZZZZ-ZZZZ/unsubmit", json={}).status_code == 404


def test_test_token_is_treated_as_nonexistent(admin, booth, monkeypatch, conn):
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    new_session(admin, booth)
    admin.post("/api/admin/test/arm-win", json={})
    token = roll(admin, booth).json()["won_token"]
    assert conn.execute("SELECT is_test FROM wins WHERE token=?", (token,)).fetchone()[0] == 1
    assert admin.get(f"/api/admin/tokens/{token}").json()["exists"] is False
    assert admin.post(f"/api/admin/tokens/{token}/submit", json={}).status_code == 404
    assert conn.execute("SELECT submitted_at FROM wins WHERE token=?", (token,)).fetchone()[0] is None


def test_token_endpoints_admin_only(admin, booth, other_clients, monkeypatch):
    token = real_win(other_clients(), booth, monkeypatch)
    v, anon = volunteer(other_clients), other_clients()
    for who, code in ((v, 403), (anon, 401)):
        assert who.get(f"/api/admin/tokens/{token}").status_code == code
        assert who.post(f"/api/admin/tokens/{token}/submit", json={}).status_code == code
        assert who.post(f"/api/admin/tokens/{token}/unsubmit", json={}).status_code == code


def test_win_record_has_no_session_link(booth, client, monkeypatch, conn):
    """§4.3: zapisujemy token, czas, wzór i stoisko; wpis nie wskazuje sesji gracza."""
    token = real_win(client, booth, monkeypatch)
    assert conn.execute("SELECT session_id FROM wins WHERE token=?", (token,)).fetchone()[0] is None
    # certyfikat tego samego gracza da się odtworzyć z jego sesji
    me = client.get("/api/game/me").json()
    assert me["won_token"] == token and me["has_won"] is True


# --- Puchar: jeden głos z urządzenia (§3.5) i zapis (§3.4) ----------------------
def test_one_vote_per_device_keeps_token_valid(admin, booth, other_clients, conn):
    c1, c2 = make_code(admin, booth_id=booth), make_code(admin, booth_id=booth)
    dev = "ab" * 32
    p = other_clients()
    assert register(p, c1, "W4N", device=dev).status_code == 200
    r = register(p, c2, "W3", device=dev)
    assert r.status_code == 409 and r.json()["detail"] == "Z tego urządzenia oddano już głos w Pucharze."
    # token nie został zużyty: student może wpisać go z innego urządzenia
    assert conn.execute("SELECT status, used_at FROM registration_codes WHERE code=?", (c2,)).fetchone()[:] == ("ACTIVE", None)
    assert p.get(f"/api/donor/check-code?kod={c2}").json()["valid"] is True
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 1
    assert register(other_clients(), c2, "W3", device="cd" * 32).status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 2


def test_same_device_ext_blocks_even_with_other_base(admin, booth, conn):
    """Skrót głosu pochodzi z device_ext (gdy jest): ten sam egzemplarz = jeden głos, inny egzemplarz = własny głos."""
    c = [make_code(admin, booth_id=booth) for _ in range(3)]
    assert register(admin, c[0], device="aa" * 32, device_ext="e1" * 32).status_code == 200
    assert register(admin, c[1], device="bb" * 32, device_ext="e1" * 32).status_code == 409
    assert register(admin, c[2], device="aa" * 32, device_ext="e2" * 32).status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 2


def test_cup_device_hash_is_stable_hmac_with_fixed_salt(admin, booth, conn, monkeypatch):
    ext = "e1" * 32
    register(admin, make_code(admin, booth_id=booth), device="aa" * 32, device_ext=ext)
    h = conn.execute("SELECT device_hash FROM donors_stats").fetchone()[0]
    assert h == hmac.new(config.secret_key().encode(), b"cup:" + ext.encode(), "sha256").hexdigest()[:32]
    assert ext not in h and "aa" * 32 not in h
    # sól dobowa nie wpływa na skrót (musi pokryć całą akcję)
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    db.rotate_device_salt()
    assert conn.execute("SELECT device_hash FROM donors_stats").fetchone()[0] == h
    assert register(admin, make_code(admin, booth_id=booth), device="aa" * 32, device_ext=ext).status_code == 409
    # unikalność pilnuje też sam indeks
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO donors_stats(faculty,created_at,device_hash) VALUES('W1','2026-12-08T10:00:00Z',?)", (h,))
    conn.execute("INSERT INTO donors_stats(faculty,created_at) VALUES('W1','2026-12-08T10:00:00Z')")  # NULL-e się nie kłócą
    conn.execute("INSERT INTO donors_stats(faculty,created_at) VALUES('W1','2026-12-08T10:00:00Z')")


def test_register_records_only_faculty_time_hash_and_voids_token(admin, booth, client, conn):
    code = make_code(admin, booth_id=booth)
    assert register(client, code, "W13").status_code == 200
    row = conn.execute("SELECT * FROM donors_stats").fetchone()
    assert set(row.keys()) == {"id", "faculty", "created_at", "device_hash"} and row["faculty"] == "W13"
    assert conn.execute("SELECT status FROM registration_codes WHERE code=?", (code,)).fetchone()[0] == "USED"
    assert register(client, code, "W13").status_code == 410  # token unieważniony


def test_register_response_promises_nothing(admin, booth, client):
    r = register(client, make_code(admin, booth_id=booth))
    assert set(r.json()) == {"ok", "faculty", "faculty_name", "booth_name", "kind"}


# --- terminy (CUP_DEADLINE, CONTEST_DEADLINE) -----------------------------------
def test_default_deadlines_and_message():
    assert config.cup_deadline() == datetime(2026, 12, 11, 15, 30, tzinfo=timezone.utc)
    assert config.contest_deadline() == datetime(2026, 12, 11, 15, 0, tzinfo=timezone.utc)
    assert config.cup_closed_message() == "Zliczanie punktów zakończone 11 grudnia 2026 o 16:30."


def test_cup_closes_at_deadline_boundary(admin, booth, client, other_clients, monkeypatch):
    monkeypatch.setenv("CODE_TTL_MINUTES", "200000")  # token z dziś jest jeszcze ważny w dniu terminu
    v = volunteer(other_clients)  # sesja wolontariusza nie zależy od zegara aplikacji (admina tak)
    code = make_code(v)
    deadline = config.cup_deadline()
    set_clock(monkeypatch, deadline - timedelta(seconds=1))
    assert register(client, code).status_code == 200
    set_clock(monkeypatch, deadline)
    r = v.post("/api/volunteer/generate-code", json={})
    assert r.status_code == 410 and r.json()["detail"] == "Zliczanie punktów zakończone 11 grudnia 2026 o 16:30."
    r = register(client, "C13-AAAA")
    assert r.status_code == 410 and r.json()["detail"] == "Zliczanie punktów zakończone 11 grudnia 2026 o 16:30."


def test_deadline_env_override_and_surfaces(admin, booth, client, monkeypatch, conn):
    code = make_code(admin, booth_id=booth)
    monkeypatch.setenv("CUP_DEADLINE", "2020-01-02T09:05")
    monkeypatch.setenv("CONTEST_DEADLINE", "2020-01-02T08:00")
    assert register(client, code).status_code == 410
    assert conn.execute("SELECT status FROM registration_codes WHERE code=?", (code,)).fetchone()[0] == "ACTIVE"  # nic nie zużyto
    msg = "Zliczanie punktów zakończone 2 stycznia 2020 o 09:05."
    assert admin.post("/api/volunteer/generate-code", json={"booth_id": booth}).json()["detail"] == msg
    me = admin.get("/api/volunteer/me?booth_id=c13").json()
    assert me["cup_closed"] is True and me["cup_closed_message"] == msg
    cup = client.get("/api/stats/cup").json()
    assert cup["cup_closed"] is True and cup["cup_closed_message"] == msg
    cfg = client.get("/api/config").json()
    assert cfg["cup_deadline"] == "2020-01-02T08:05:00Z" and cfg["contest_deadline"] == "2020-01-02T07:00:00Z"
    monkeypatch.setenv("CUP_DEADLINE", "bzdura")  # zła wartość = domyślny termin
    assert config.cup_deadline() == datetime(2026, 12, 11, 15, 30, tzinfo=timezone.utc)
    # start nie jest blokowany: przed terminem wszystko działa
    monkeypatch.delenv("CUP_DEADLINE")
    assert register(client, code).status_code == 200
    assert admin.get("/api/volunteer/me?booth_id=c13").json()["cup_closed"] is False


# --- schemat po migracji --------------------------------------------------------
def test_no_card_or_study_year_anywhere_in_schema(client, conn):
    ddl = " ".join(r[0] or "" for r in conn.execute("SELECT sql FROM sqlite_master"))
    for forbidden in ("card_hash", "actual_donor_cards", "study_year", "registered_date", "promo_codes", "bonus_attempts"):
        assert forbidden not in ddl, forbidden
    assert not (Path(db.__file__).parent / "cards.py").exists()


def test_faculties_endpoint_has_no_study_years(client):
    assert set(client.get("/api/dictionary/faculties").json()) == {"faculties"}


# --- migracja ze schematu iteracji 6 (produkcja) --------------------------------
def build_old_db(path):
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    ts = "2026-10-31T10:00:00Z"
    raw.execute("INSERT INTO booths VALUES('c13','C-13','x','0123012301',?,3,9,?, 'C-13', NULL, NULL)", (ts, ts))
    raw.execute("INSERT INTO donors_stats(booth_id,faculty,study_year,registered_date,kind) VALUES('c13','W4N',3,'2026-10-31','potential')")
    raw.execute("INSERT INTO donors_stats(booth_id,faculty,study_year,registered_date,kind) VALUES('c13','W3',1,'2026-11-01','actual')")
    raw.execute("INSERT INTO registration_codes VALUES('C13-AAAA','c13','USED',?,?,'actual','CARDHASH')", (ts, ts))
    raw.execute("INSERT INTO registration_codes VALUES('C13-BBBB','c13','ACTIVE',?,NULL,'potential',NULL)", (ts,))
    raw.execute("INSERT INTO actual_donor_cards VALUES('CARDHASH','2026-10-31')")
    raw.execute("INSERT INTO promo_codes VALUES('C13-CCCC','c13','USED',?,?)", (ts, ts))
    raw.execute("INSERT INTO game_sessions(session_id,created_at,has_won,bonus_attempts,won_genotype,won_at,won_token,device_key) "
                "VALUES('s1',?,1,15,'0123012301',?,'HG-AAAA-BBBB','k1')", (ts, ts))
    raw.execute("INSERT INTO wins VALUES('HG-AAAA-BBBB',1,'0123012301','c13',?,'s1',0)", (ts,))
    raw.execute("INSERT INTO settings VALUES('facebook_url','')")
    raw.commit()
    raw.close()


def test_migration_from_iteration_6_keeps_data_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    build_old_db(config.db_path())
    snapshots = []
    for _ in range(2):
        db.init_db()
        conn = db.connect()
        cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert not {"promo_codes", "actual_donor_cards", "donors_stats_new"} & names
        assert cols("donors_stats") == {"id", "faculty", "created_at", "device_hash"}
        assert "bonus_attempts" not in cols("game_sessions") and "card_hash" not in cols("registration_codes")
        assert "submitted_at" in cols("wins") and "idx_donors_device" in names
        rows = conn.execute("SELECT faculty, created_at, device_hash FROM donors_stats ORDER BY id").fetchall()
        assert [(r["faculty"], config.warsaw_date(r["created_at"]), r["device_hash"]) for r in rows] == \
            [("W4N", "2026-10-31", None), ("W3", "2026-11-01", None)]
        w = conn.execute("SELECT * FROM wins").fetchone()
        assert (w["token"], w["session_id"], w["submitted_at"]) == ("HG-AAAA-BBBB", None, None)
        assert conn.execute("SELECT won_token FROM game_sessions").fetchone()[0] == "HG-AAAA-BBBB"  # certyfikat gracza zostaje
        # typ i stoisko dalej da się policzyć ze zużytych tokenów
        assert db.used_counts(conn, "c13") == {"actual": 1}
        assert conn.execute("SELECT kind FROM registration_codes WHERE code='C13-BBBB'").fetchone()[0] == "potential"
        assert [r["slug"] for r in conn.execute("SELECT slug FROM legal_documents ORDER BY sort")] == list(legal.BASE_SLUGS)
        assert db.get_setting(conn, "facebook_url") == "https://www.facebook.com/samorzadpwr"
        snapshots.append([tuple(r) for r in conn.execute("SELECT * FROM legal_documents")] +
                         [tuple(r) for r in conn.execute("SELECT * FROM donors_stats")])
        conn.close()
    assert snapshots[0] == snapshots[1]  # drugi start niczego nie zmienia (w tym dat dokumentów)


def test_migration_on_fresh_db_and_seed_never_overwrites_edits(client, conn, admin):
    assert conn.execute("SELECT COUNT(*) FROM legal_documents").fetchone()[0] == 3
    admin.put("/api/admin/legal/polityka-prywatnosci", json={"body_md": "## Zmieniona\n\nTreść."})
    db.init_db()
    db.init_db()
    row = conn.execute("SELECT body_md, version FROM legal_documents WHERE slug='polityka-prywatnosci'").fetchone()
    assert row["body_md"] == "## Zmieniona\n\nTreść." and row["version"] == 2


# --- dokumenty prawne -----------------------------------------------------------
def test_seed_matches_the_two_regulations_verbatim(client, conn):
    for slug in ("regulamin-konkursu", "regulamin-pucharu"):
        source = (LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8")
        row = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
        assert source == f"# {row['title']}\n\n{row['body_md']}"  # ani słowa zmian
        assert (row["version"], row["published"]) == (1, 1)
    titles = {r["slug"]: r["title"] for r in conn.execute("SELECT slug, title FROM legal_documents")}
    assert titles["regulamin-konkursu"] == "Regulamin akcji edukacyjnej i konkursu „HLA Match Maker – Sprawdź Parametry”"
    assert titles["regulamin-pucharu"].endswith("„Puchar Dawcy PWr”") and titles["polityka-prywatnosci"] == "Polityka prywatności"
    assert [r[0] for r in conn.execute("SELECT slug FROM legal_documents ORDER BY sort")] == list(legal.BASE_SLUGS)


def test_public_pages_show_date_and_version(client, admin, conn):
    assert admin.put("/api/admin/legal/regulamin-pucharu", json={"title": "Regulamin Pucharu 2"}).json()["version"] == 2
    conn.execute("UPDATE legal_documents SET updated_at='2026-11-01T13:30:05Z' WHERE slug IN ('regulamin-pucharu','regulamin-konkursu')")
    page = client.get("/dokumenty/regulamin-pucharu")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "Ostatnia zmiana: 1 listopada 2026, 14:30" in page.text and "Wersja 2" in page.text
    assert "<h1>Regulamin Pucharu 2</h1>" in page.text and "<title>Regulamin Pucharu 2 · " in page.text
    assert "<h2>§1. Postanowienia ogólne i Organizator</h2>" in page.text
    assert "Wskaźnik Zaangażowania" in page.text and '/static/v/' in page.text and "{{" not in page.text
    lst = client.get("/dokumenty").text
    assert "Ostatnia zmiana: 1 listopada 2026, 14:30" in lst and 'href="/dokumenty/regulamin-konkursu"' in lst
    assert client.get("/dokumenty/nie-ma-takiego").status_code == 404
    assert client.get("/dokumenty/ZLY_SLUG!").status_code == 404


def test_old_legal_urls_redirect(client):
    r = client.get("/regulamin", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/dokumenty"
    r = client.get("/polityka-prywatnosci", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/dokumenty/polityka-prywatnosci"
    assert not (Path(config.__file__).parent / "static" / "regulamin.html").exists()
    assert not (Path(config.__file__).parent / "static" / "polityka-prywatnosci.html").exists()


def test_public_legal_api_and_config_date(client, admin, monkeypatch):
    d = client.get("/api/legal").json()
    assert [x["slug"] for x in d["documents"]] == list(legal.BASE_SLUGS)
    assert set(d["documents"][0]) == {"slug", "title", "updated_at", "version"}
    assert d["latest_update"] == max(x["updated_at"] for x in d["documents"])
    before = client.get("/api/config").json()["legal_updated_at"]
    assert before == max(x["updated_at"] for x in d["documents"] if x["slug"] in ("regulamin-konkursu", "polityka-prywatnosci"))
    # regulamin Pucharu nie wymusza ponownej zgody w symulatorze, konkursu i polityki tak
    set_clock(monkeypatch, config.now() + timedelta(hours=1))
    admin.put("/api/admin/legal/regulamin-pucharu", json={"body_md": "Nowe zasady."})
    assert client.get("/api/config").json()["legal_updated_at"] == before
    admin.put("/api/admin/legal/polityka-prywatnosci", json={"body_md": "Nowa polityka."})
    assert client.get("/api/config").json()["legal_updated_at"] > before


def test_legal_create_validation_and_listing(admin):
    for bad in ("ab", "A-bcd", "zły_slug", "a" * 61, "spa cja", "ąęć-test"):
        assert admin.post("/api/admin/legal", json={"slug": bad, "title": "T", "body_md": "x"}).status_code == 422, bad
    assert admin.post("/api/admin/legal", json={"slug": "okok", "title": "  ", "body_md": "x"}).status_code == 422
    r = admin.post("/api/admin/legal", json={"slug": "zasady-dodatkowe", "title": "Zasady dodatkowe", "body_md": "## A\n\nTreść"})
    assert r.status_code == 201 and r.json()["version"] == 1
    assert admin.post("/api/admin/legal", json={"slug": "zasady-dodatkowe", "title": "X", "body_md": "y"}).status_code == 409
    rows = admin.get("/api/admin/legal").json()
    assert [x["slug"] for x in rows] == [*legal.BASE_SLUGS, "zasady-dodatkowe"]
    assert [x["base"] for x in rows] == [True, True, True, False]
    one = admin.get("/api/admin/legal/zasady-dodatkowe").json()
    assert one["title"] == "Zasady dodatkowe" and one["body_md"] == "## A\n\nTreść" and one["versions"] == [] and one["published"] is True
    assert admin.get("/api/admin/legal/nie-ma").status_code == 404
    big = {"slug": "wielki", "title": "T", "body_md": "a" * 200_001}
    assert admin.post("/api/admin/legal", json=big).status_code == 422
    assert admin.post("/api/admin/legal", json={**big, "body_md": "ą" * 100_001}).status_code == 422  # limit w bajtach
    assert admin.post("/api/admin/legal", json={**big, "body_md": "a" * 200_000}).status_code == 201


def test_version_and_date_change_only_with_title_or_body(admin, client, monkeypatch):
    # sesja admina ważna 12 h, więc zegar przesuwamy tylko o godziny
    t0 = config.now().replace(microsecond=0)
    stamp = lambda h: config.iso(t0 + timedelta(hours=h))
    set_clock(monkeypatch, t0)
    admin.post("/api/admin/legal", json={"slug": "dokument-testowy", "title": "Tytuł", "body_md": "Treść 1"})
    created = admin.get("/api/admin/legal/dokument-testowy").json()
    assert (created["version"], created["updated_at"]) == (1, stamp(0))

    set_clock(monkeypatch, t0 + timedelta(hours=1))
    r = admin.put("/api/admin/legal/dokument-testowy", json={"body_md": "Treść 2"})
    assert r.json() == {"slug": "dokument-testowy", "version": 2, "updated_at": stamp(1)}
    # zmiana tylko widoczności i kolejności nie rusza wersji ani daty
    set_clock(monkeypatch, t0 + timedelta(hours=2))
    r = admin.put("/api/admin/legal/dokument-testowy", json={"published": False, "sort": 50})
    assert r.json()["version"] == 2 and r.json()["updated_at"] == stamp(1)
    # te same treść i tytuł (także z CRLF) to nie zmiana
    admin.put("/api/admin/legal/dokument-testowy", json={"published": True})
    r = admin.put("/api/admin/legal/dokument-testowy", json={"title": "Tytuł", "body_md": "Treść 2"})
    assert r.json()["version"] == 2 and r.json()["updated_at"] == stamp(1)
    # datę i wersję ustawia wyłącznie serwer
    r = admin.put("/api/admin/legal/dokument-testowy", json={"title": "Tytuł 3", "version": 99, "updated_at": "2001-01-01T00:00:00Z"})
    assert r.json() == {"slug": "dokument-testowy", "version": 3, "updated_at": stamp(2)}
    # historia: stan sprzed każdej zmiany
    one = admin.get("/api/admin/legal/dokument-testowy").json()
    assert [(v["version"], v["title"], v["saved_by"]) for v in one["versions"]] == [(2, "Tytuł", "admin"), (1, "Tytuł", "admin")]
    assert admin.get("/api/admin/legal/dokument-testowy/versions/1").json()["body_md"] == "Treść 1"
    v2 = admin.get("/api/admin/legal/dokument-testowy/versions/2").json()
    assert v2["body_md"] == "Treść 2" and v2["saved_at"] == stamp(2)
    assert admin.get("/api/admin/legal/dokument-testowy/versions/3").status_code == 404  # bieżąca wersja nie jest archiwum
    assert admin.put("/api/admin/legal/nie-ma", json={"title": "x"}).status_code == 404
    assert admin.put("/api/admin/legal/dokument-testowy", json={"title": " "}).status_code == 422
    assert admin.put("/api/admin/legal/dokument-testowy", json={"body_md": "a" * 200_001}).status_code == 422


def test_unpublished_is_404_but_listed_for_admin(admin, client):
    admin.post("/api/admin/legal", json={"slug": "ukryty-dokument", "title": "Ukryty", "body_md": "tajne"})
    assert client.get("/dokumenty/ukryty-dokument").status_code == 200
    admin.put("/api/admin/legal/ukryty-dokument", json={"published": False})
    assert client.get("/dokumenty/ukryty-dokument").status_code == 404
    assert "ukryty-dokument" not in client.get("/dokumenty").text
    assert "ukryty-dokument" not in [d["slug"] for d in client.get("/api/legal").json()["documents"]]
    assert "ukryty-dokument" in [d["slug"] for d in admin.get("/api/admin/legal").json()]


def test_base_documents_protected(admin, client):
    for slug in legal.BASE_SLUGS:
        r = admin.delete(f"/api/admin/legal/{slug}", headers=JSON)
        assert r.status_code == 409, slug
        assert admin.put(f"/api/admin/legal/{slug}", json={"published": False}).status_code == 409, slug
        assert client.get(f"/dokumenty/{slug}").status_code == 200
        assert admin.put(f"/api/admin/legal/{slug}", json={"sort": 7, "published": True}).status_code == 200  # sort wolno
    assert admin.delete("/api/admin/legal/nie-ma", headers=JSON).status_code == 404


def test_delete_custom_document_removes_history(admin, conn):
    admin.post("/api/admin/legal", json={"slug": "do-usuniecia", "title": "A", "body_md": "1"})
    admin.put("/api/admin/legal/do-usuniecia", json={"body_md": "2"})
    assert conn.execute("SELECT COUNT(*) FROM legal_document_versions WHERE slug='do-usuniecia'").fetchone()[0] == 1
    assert admin.delete("/api/admin/legal/do-usuniecia", headers=JSON).json() == {"ok": True}
    assert conn.execute("SELECT COUNT(*) FROM legal_document_versions WHERE slug='do-usuniecia'").fetchone()[0] == 0
    assert admin.get("/api/admin/legal/do-usuniecia").status_code == 404


def test_markdown_render_has_no_raw_html_or_script_links(admin, client):
    evil = ("# H\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n\n[kliknij](javascript:alert(3))\n\n"
            "[ok](https://example.com/a)\n\n[vb](vbscript:x) <a href=\"javascript:alert(4)\">raw</a>\n\n**pogrubione**")
    admin.post("/api/admin/legal", json={"slug": "zlosliwy", "title": "T <b>x</b> & \"q\"", "body_md": evil})
    page = client.get("/dokumenty/zlosliwy").text
    body = re.search(r'<article class="card doc-body">(.*)</article>', page, re.S).group(1)
    assert "<script" not in page and "<img" not in body and "<a href=\"javascript" not in body
    assert 'href="javascript' not in body and 'href="vbscript' not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "&lt;img src=x onerror=alert(2)&gt;" in body
    assert '<a href="https://example.com/a">ok</a>' in body and "<strong>pogrubione</strong>" in body
    assert "<h1>T &lt;b&gt;x&lt;/b&gt; &amp; " in page and "<b>x</b>" not in page
    prev = admin.post("/api/admin/legal/preview", json={"body_md": evil}).json()["html"]
    assert "<script" not in prev and "<img" not in prev and 'href="javascript' not in prev and "<strong>pogrubione</strong>" in prev
    assert admin.post("/api/admin/legal/preview", json={"body_md": "a" * 200_001}).status_code == 422


def test_contact_placeholder_is_substituted_and_escaped(admin, client, monkeypatch):
    monkeypatch.delenv("LEGAL_CONTACT", raising=False)
    page = client.get("/dokumenty/polityka-prywatnosci").text
    assert "{{CONTACT}}" not in page and "[do uzupełnienia]" in page
    monkeypatch.setenv("LEGAL_CONTACT", 'a@b.pl <i>"x"</i>')
    page = client.get("/dokumenty/polityka-prywatnosci").text
    assert "a@b.pl &lt;i&gt;&quot;x&quot;&lt;/i&gt;" in page and "<i>" not in page
    prev = admin.post("/api/admin/legal/preview", json={"body_md": "Kontakt: {{CONTACT}}"}).json()["html"]
    assert "a@b.pl &lt;i&gt;" in prev
    assert not hasattr(config, "legal_owner") and "{{OWNER}}" not in page
    admin.post("/api/admin/legal", json={"slug": "bez-kontaktu", "title": "T", "body_md": "{{OWNER}} zostaje"})
    assert "{{OWNER}} zostaje" in client.get("/dokumenty/bez-kontaktu").text  # OWNER już nie istnieje


def test_privacy_policy_matches_new_mechanics(client, conn):
    body = conn.execute("SELECT body_md FROM legal_documents WHERE slug='polityka-prywatnosci'").fetchone()[0]
    low = body.lower()
    for needed in ("wybrzeżu wyspiańskiego 27", "token losu", "hp_game", "hp_consent", "hp_staff", "12 godzin", "14 godzin",
                   "turnstile", "facebook", "{{contact}}", "6 miesięcy"):
        assert needed in low, needed
    for gone in ("bonus", "rok studiów", "roku studiów", "dodatkowe losy", "{{owner}}", "automatycznie usuwamy", "skrót hmac numeru"):
        assert gone not in low, gone
    assert "nie jest to proces automatyczny" in low


def test_legal_admin_endpoints_need_admin(booth, other_clients):
    v, anon = volunteer(other_clients), other_clients()
    calls = [("get", "/api/admin/legal", None), ("get", "/api/admin/legal/regulamin-konkursu", None),
             ("post", "/api/admin/legal", {"slug": "abc", "title": "t", "body_md": "b"}),
             ("put", "/api/admin/legal/regulamin-konkursu", {"title": "x"}),
             ("post", "/api/admin/legal/preview", {"body_md": "x"}),
             ("get", "/api/admin/legal/regulamin-konkursu/versions/1", None)]
    for who, code in ((v, 403), (anon, 401)):
        for method, path, body in calls:
            r = getattr(who, method)(path, **({"json": body} if body is not None else {}))
            assert r.status_code == code, (method, path, r.status_code)
    assert anon.delete("/api/admin/legal/abc", headers=JSON).status_code == 401
    assert v.delete("/api/admin/legal/abc", headers=JSON).status_code == 403


# --- zależności i nazewnictwo ---------------------------------------------------
def test_requirements_list_markdown_dependency():
    req = (Path(config.__file__).parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "markdown-it-py" in req


def test_footer_and_nav_naming_in_served_pages(client):
    for url in ("/", "/graj", "/potwierdz", "/puchar", "/statystyki", "/login", "/dokumenty", "/dokumenty/regulamin-pucharu"):
        text = client.get(url).text
        assert "Organizator: Samorząd Studencki Politechniki Wrocławskiej, we współpracy z zespołem akcji Helpers' Generation." in text, url
        assert "Nie jest oficjalną stroną Fundacji DKMS." in text, url
        assert 'href="/dokumenty"' in text and 'href="/dokumenty/polityka-prywatnosci"' in text, url
        assert "Bitwa" not in text and "href=\"/bitwa\"" not in text and "{{" not in text.replace("{{CONTACT}}", ""), url
    assert "Puchar Dawcy PWr" in client.get("/puchar").text and "Wskaźnik Zaangażowania" in client.get("/puchar").text
    assert "Ranking orientacyjny. Oficjalne wyniki po audycie: 13 grudnia 2026." in client.get("/puchar").text
    graj = client.get("/graj").text
    assert "Sprawdź parametry" in graj and ">Losuj<" not in graj and "Token Losu" in graj
    assert "1 do 1 000 000" in graj and "Zgłoszenia do konkursu zostały zamknięte." in graj and "@samorzadpwr" in graj
    assert "upominek" not in graj.lower() and "dodatkowe próby" not in graj.lower()


def test_static_sources_have_no_removed_features_or_long_dashes():
    static = Path(config.__file__).parent / "static"
    for f in list(static.glob("*.html")) + list(static.glob("*.js")):
        text = f.read_text(encoding="utf-8")
        assert "—" not in text, f.name
        for gone in ("hp_bonus'", "redeem-promo", "card-number", "study-year", "Dodatkowe losy", "per_1000", "api/stats/battle"):
            if f.name == "graj.js" and gone == "hp_bonus'":
                continue  # graj.js tylko czyści dawny klucz
            assert gone not in text, (f.name, gone)
        assert not re.search(r"\son[a-z]+=\"", text), f.name  # żadnego inline JS w HTML
    assert "ti ti-" in (static / "graj.html").read_text(encoding="utf-8")
