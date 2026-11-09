"""v3: sesja bez odcisku urządzenia, kod QR Pucharu (bezstanowy, 60 s), kategorie, post, ekran stoiska, partnerzy, termin z panelu."""
import json
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, db, legal, qrtoken

from test_api import claim, cup_token, enter, new_session, vote, vote_new, volunteer, voter
from test_iter3 import roll, set_clock

EXPIRED = "Kod wygasł. Podejdź do stanowiska po nowy kod"
BAD = "Nieprawidłowy kod QR. Podejdź do stanowiska po nowy kod."


# --- limit prób na sesję i stanowisko ---------------------------------------------
def test_pool_per_session_and_booth_and_day(admin, booth, monkeypatch):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    a, b = voter(), voter()
    new_session(a, booth)
    new_session(b, booth)
    for _ in range(5):
        assert roll(a, booth).status_code == 200
    assert roll(a, booth).status_code == 429
    assert roll(b, booth).status_code == 200            # nowa sesja ma własne 5
    assert enter(a, "w4").status_code == 200 and roll(a, "w4").status_code == 200   # inne stoisko: własne 5
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert enter(a, booth).status_code == 200
    assert roll(a, booth).status_code == 200            # następny dzień: pula wraca


def test_bonus_after_pool_survives_midnight(admin, booth, monkeypatch):
    a = voter()
    new_session(a, booth)
    vote(a, booth)                                       # +10
    for _ in range(5):
        roll(a, booth)
    assert roll(a, booth).json()["bonus_attempts"] == 9
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert a.get("/api/game/me").json()["bonus_attempts"] == 9


def test_cookie_only_and_flags(client, booth, monkeypatch):
    r = client.post("/api/game/session", json={})
    sc = r.headers["set-cookie"].lower()
    assert "hp_game=" in sc and "httponly" in sc and "samesite=lax" in sc and "secure" not in sc
    monkeypatch.setenv("COOKIE_SECURE", "1")
    r = voter().post("/api/game/session", json={})
    assert "secure" in r.headers["set-cookie"].lower()
    token = client.cookies.get("hp_game")
    other = voter()
    assert other.get("/api/game/me", headers={"X-Game-Token": token}).status_code == 401


# --- token QR Pucharu ---------------------------------------------------------------
def test_cup_token_window(admin, booth, monkeypatch):
    t0 = config.now()
    set_clock(monkeypatch, t0)
    tok = cup_token(booth, "nowy")
    for sec in (0, 60, 65):
        set_clock(monkeypatch, t0 + timedelta(seconds=sec))
        assert voter().post("/api/cup/claim", json={"t": tok}).status_code == 200, sec
    set_clock(monkeypatch, t0 + timedelta(seconds=66))
    r = voter().post("/api/cup/claim", json={"t": tok})
    assert r.status_code == 410 and r.json()["detail"] == EXPIRED


def test_cup_token_tampered_and_foreign(admin, booth, monkeypatch):
    tok = cup_token(booth, "nowy")
    parts = tok.split(".")
    for bad in (tok[:-1] + ("A" if tok[-1] != "A" else "B"), ".".join([parts[0], "f", *parts[2:]]), "x", "", "a.b.c.d.e",
                qrtoken.current(booth), tok + "x" * 100):
        r = voter().post("/api/cup/claim", json={"t": bad})
        assert r.status_code == 400 and r.json()["detail"] == BAD, bad
    # przyszłość o więcej niż 5 s
    real = config.now()
    set_clock(monkeypatch, real + timedelta(seconds=30))
    future = cup_token(booth, "nowy")
    set_clock(monkeypatch, real)
    assert voter().post("/api/cup/claim", json={"t": future}).status_code == 400
    # nieznane stoisko i stoisko zajęć
    assert voter().post("/api/cup/claim", json={"t": qrtoken.cup_issue("nope", "nowy")[0]}).status_code == 404
    assert voter().post("/api/cup/claim", json={"t": qrtoken.cup_issue("zajecia", "nowy")[0]}).status_code == 404


def test_cup_token_multi_use_two_sessions(admin, booth):
    tok = cup_token(booth, "zarejestrowany")
    for _ in range(2):
        c = voter()
        assert c.post("/api/cup/claim", json={"t": tok}).status_code == 200
        assert c.post("/api/cup/vote", json={"faculty": "W4N", "study_year": "I2"}).status_code == 200
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 2
    conn.close()


def test_vote_bonuses_and_errors(admin, booth, monkeypatch):
    for cat, bonus in (("nowy", 10), ("zarejestrowany", 10), ("faktyczny", 20)):
        d = vote_new(booth, cat).json()
        assert d["bonus_attempts_granted"] == bonus and d["attempts_left"] == 5 + bonus and d["category"] == cat
    # głos bez claimu
    c = voter()
    assert c.post("/api/cup/vote", json={"faculty": "W4N", "study_year": "I1"}).status_code == 403
    # claim wygasa po 10 minutach
    c = voter()
    assert claim(c, booth).status_code == 200
    real = config.now()
    set_clock(monkeypatch, real + timedelta(minutes=config.CUP_CLAIM_MINUTES + 1))
    r = c.post("/api/cup/vote", json={"faculty": "W4N", "study_year": "I1"})
    assert r.status_code == 403 and r.json()["detail"] == EXPIRED
    set_clock(monkeypatch, real)
    c = voter()
    claim(c, booth)
    assert c.post("/api/cup/vote", json={"faculty": "ZZ", "study_year": "I1"}).status_code == 422
    assert c.post("/api/cup/vote", json={"faculty": "W4N", "study_year": "X9"}).status_code == 422
    assert c.get("/api/cup/me").json()["claim"]["category"] == "nowy"


def test_cup_deadline_blocks_vote_not_post(admin, booth, monkeypatch):
    c = voter()
    claim(c, booth)
    monkeypatch.setattr(config, "cup_closed", lambda: True)
    assert claim(voter(), booth, "nowy").status_code == 410
    assert c.post("/api/cup/vote", json={"faculty": "W4N", "study_year": "I1"}).status_code == 410
    assert admin.get(f"/api/volunteer/cup-qr?category=faktyczny&booth_id={booth}").status_code == 410
    assert claim(voter(), booth, "post").status_code == 200


def test_post_bonus_once_per_day(admin, booth, monkeypatch, conn):
    c = voter()
    d = claim(c, booth, "post").json()
    assert d["kind"] == "post" and d["bonus_attempts_granted"] == 5 and d["attempts_left"] == 10
    assert d["play_path"].startswith(f"/graj?stoisko={booth}&t=")
    r = claim(c, booth, "post")
    assert r.status_code == 409 and r.json()["detail"] == "Dodatkowe próby za post zostały już dziś odebrane."
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 0
    assert c.get("/api/cup/me").json()["post_today"] is True
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert claim(c, booth, "post").status_code == 200
    assert c.get("/api/game/me").json()["bonus_attempts"] == 10


# --- kod QR w panelu wolontariusza -------------------------------------------------
def test_cup_qr_endpoint(admin, booth, other_clients):
    anon = other_clients()
    assert anon.get("/api/volunteer/cup-qr?category=nowy").status_code == 401
    assert admin.get("/api/volunteer/cup-qr?category=nowy").status_code == 400
    v = volunteer(other_clients)
    assert v.get("/api/volunteer/cup-qr?category=zly").status_code == 422
    assert v.get("/api/volunteer/cup-qr?category=nowy&booth_id=zzz").status_code == 403
    r = v.get("/api/volunteer/cup-qr?category=faktyczny").json()
    assert r["valid_seconds"] == 60 and r["booth"]["id"] == booth and r["expires_at"] - r["issued_at"] == 60
    assert r["path"].startswith("/potwierdz?t=")
    assert qrtoken.cup_verify(r["path"].split("t=")[1]) == (booth, "faktyczny")
    assert admin.get("/api/volunteer/cup-qr?category=post&booth_id=zajecia").status_code == 409
    assert admin.get("/api/volunteer/cup-qr?category=nowy&booth_id=nope").status_code == 404


# --- ekran stoiska tylko dla personelu ---------------------------------------------
def test_stoisko_requires_staff(client, booth, other_clients):
    from app.main import STATIC_DIR
    anon = other_clients()
    r = anon.get("/stoisko/c13", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fstoisko%2Fc13"
    assert volunteer(other_clients).get("/stoisko/c13").status_code == 200
    token = client.get("/api/admin/lecture-screen")
    client.post("/api/auth/login", json={"login": "admin", "password": "test-admin-secret"})
    t = client.get("/api/admin/lecture-screen").json()["token"]
    assert anon.get(f"/zajecia/{t}").status_code == 200


def test_removed_endpoints(admin, booth):
    for path in ("/api/donor/register", "/api/donor/check-code", "/api/donor/redeem-promo", "/api/volunteer/generate-code",
                 "/api/admin/codes"):
        assert admin.post(path, json={}).status_code in (404, 405)
        assert admin.get(path).status_code in (404, 405)


# --- partnerzy: kolejność ----------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def add_partner(c, name):
    import base64
    r = c.post("/api/admin/partners", json={"name": name, "filename": "x.png", "data_base64": base64.b64encode(PNG).decode()})
    assert r.status_code == 201
    return r.json()["id"]


def test_partner_order(admin, booth, other_clients):
    ids = [add_partner(admin, n) for n in "ABC"]
    assert [p["id"] for p in admin.get("/api/partners").json()] == ids
    new = [ids[2], ids[0], ids[1]]
    r = admin.put("/api/admin/partners/order", json={"ids": new})
    assert r.status_code == 200 and [p["id"] for p in r.json()] == new
    assert [p["id"] for p in admin.get("/api/partners").json()] == new
    d = add_partner(admin, "D")
    assert [p["id"] for p in admin.get("/api/partners").json()][-1] == d
    for bad in ([], new, new + [new[0], d], [*new, 999]):
        r = admin.put("/api/admin/partners/order", json={"ids": bad})
        assert r.status_code == 422 and r.json()["detail"] == "Lista musi zawierać każdego partnera dokładnie raz.", bad
    assert volunteer(other_clients).put("/api/admin/partners/order", json={"ids": new}).status_code == 403
    assert other_clients().put("/api/admin/partners/order", json={"ids": new}).status_code == 401


# --- terminy z panelu admina --------------------------------------------------------
def test_deadlines_in_admin_settings(admin, booth, client, other_clients):
    s = admin.get("/api/admin/settings").json()
    assert s["cup_deadline"] == {"value": "2026-12-11T16:30", "default": "2026-12-11T16:30", "custom": False}
    assert s["contest_deadline"]["value"] == "2026-12-11T16:00"
    # termin Pucharu w przeszłości zamyka głosowanie, termin konkursu zmienia /api/config
    r = admin.put("/api/admin/settings", json={"facebook_url": "", "cup_deadline": "2020-01-02T09:05",
                                               "contest_deadline": "2020-01-02T08:00"})
    assert r.status_code == 200 and r.json()["cup_deadline"]["custom"] is True
    assert config.cup_closed() is True
    assert config.cup_closed_message() == "Zliczanie punktów zakończone 2 stycznia 2020 o 09:05."
    assert claim(voter(), "c13", "nowy").status_code == 410
    cfg = client.get("/api/config").json()
    assert cfg["cup_deadline"] == "2020-01-02T08:05:00Z" and cfg["contest_deadline"] == "2020-01-02T07:00:00Z"
    assert client.get("/api/stats/cup").json()["cup_closed"] is True
    # reset przywraca domyślne
    admin.put("/api/admin/settings", json={"facebook_url": "", "cup_deadline": "", "contest_deadline": None})
    assert config.cup_closed() is False
    assert admin.get("/api/admin/settings").json()["cup_deadline"]["custom"] is False
    assert client.get("/api/config").json()["contest_deadline"] == "2026-12-11T15:00:00Z"
    # walidacja i uprawnienia
    for bad in ("zle", "2020-13-45T99:00"):
        assert admin.put("/api/admin/settings", json={"facebook_url": "", "cup_deadline": bad}).status_code == 422
        assert admin.put("/api/admin/settings", json={"facebook_url": "", "contest_deadline": bad}).status_code == 422
    v, anon = volunteer(other_clients), other_clients()
    assert v.get("/api/admin/settings").status_code == 403
    assert v.put("/api/admin/settings", json={"facebook_url": ""}).status_code == 403
    assert anon.put("/api/admin/settings", json={"facebook_url": ""}).status_code == 401


# --- dokumenty prawne: jednorazowe podniesienie do v3 ------------------------------
def test_legal_upgrade_v3(client, conn):
    slug = "regulamin-pucharu"
    row = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
    assert row["version"] == 1 and db.get_setting(conn, "legal_seed_version") == "3"   # świeża baza: bez podbicia
    conn.execute("UPDATE legal_documents SET body_md='Stara treść v2.\n', title='Stary' WHERE slug=?", (slug,))
    conn.execute("DELETE FROM settings WHERE key='legal_seed_version'")
    legal.seed(conn)
    new = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
    assert new["version"] == 2 and new["body_md"] == row["body_md"] and new["updated_at"] >= row["updated_at"]
    hist = conn.execute("SELECT * FROM legal_document_versions WHERE slug=?", (slug,)).fetchall()
    assert [(h["version"], h["saved_by"], h["body_md"]) for h in hist] == [(1, "system", "Stara treść v2.\n")]
    assert db.get_setting(conn, "legal_seed_version") == "3"
    legal.seed(conn)   # drugi raz nic nie zmienia
    assert tuple(conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()) == tuple(new)
    # późniejsza edycja admina nie jest nadpisywana
    conn.execute("UPDATE legal_documents SET body_md='Edycja admina.\n' WHERE slug=?", (slug,))
    legal.seed(conn)
    assert conn.execute("SELECT body_md FROM legal_documents WHERE slug=?", (slug,)).fetchone()[0] == "Edycja admina.\n"


# --- migracja z bazy sprzed v3 ------------------------------------------------------
PRE_V3 = """
CREATE TABLE booths(id TEXT PRIMARY KEY, name TEXT NOT NULL, pin_hash TEXT NOT NULL, current_genotype TEXT NOT NULL,
  genotype_updated_at TEXT NOT NULL, matches_count INTEGER NOT NULL DEFAULT 0, rolls_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, building TEXT NOT NULL DEFAULT '', date_from TEXT NULL, date_to TEXT NULL,
  is_lecture INTEGER NOT NULL DEFAULT 0);
CREATE TABLE game_sessions(session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, has_won INTEGER NOT NULL DEFAULT 0,
  bonus_attempts INTEGER NOT NULL DEFAULT 0, pass_booth TEXT NULL, pass_until TEXT NULL, won_genotype TEXT NULL,
  won_at TEXT NULL, won_token TEXT NULL, consent_at TEXT NULL, device_key TEXT NULL, device_ext_key TEXT NULL);
CREATE TABLE booth_plays(device_key TEXT NOT NULL, booth_id TEXT NOT NULL, date TEXT NOT NULL, session_id TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, ext_key TEXT NOT NULL DEFAULT '', PRIMARY KEY(device_key, booth_id, date, session_id));
CREATE TABLE donors_stats(id INTEGER PRIMARY KEY AUTOINCREMENT, faculty TEXT NOT NULL, created_at TEXT NOT NULL, device_hash TEXT NULL);
CREATE UNIQUE INDEX idx_donors_device ON donors_stats(device_hash) WHERE device_hash IS NOT NULL;
CREATE TABLE cup_actual_counts(faculty TEXT PRIMARY KEY, actual INTEGER NOT NULL DEFAULT 0);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE partners(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, filename TEXT NOT NULL);
"""


def test_migration_from_pre_v3(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.executescript(PRE_V3)
    ts = "2026-11-03T10:00:00Z"
    raw.execute("INSERT INTO booths(id,name,pin_hash,current_genotype,genotype_updated_at,created_at) VALUES('c13','C','x','0123012301',?,?)", (ts, ts))
    raw.execute("INSERT INTO game_sessions(session_id,created_at,device_key,device_ext_key,bonus_attempts) VALUES('s1',?,'k','e',7)", (ts,))
    raw.execute("INSERT INTO booth_plays VALUES('k','c13','2026-11-03','s1',3,'e')")
    for fac, h in (("W4N", "a"), ("W4N", "b"), ("W3", "c")):
        raw.execute("INSERT INTO donors_stats(faculty,created_at,device_hash) VALUES(?,?,?)", (fac, ts, h))
    raw.execute("INSERT INTO cup_actual_counts VALUES('W4N',1)")
    raw.execute("INSERT INTO settings VALUES('device_salt','{}')")
    raw.execute("INSERT INTO settings VALUES('device_tolerance','10')")
    raw.execute("INSERT INTO partners(name,filename) VALUES('A','a.png')")
    raw.execute("INSERT INTO partners(name,filename) VALUES('B','b.png')")
    raw.commit()
    raw.close()
    for _ in range(2):
        db.init_db()
        conn = db.connect()
        cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        assert cols("donors_stats") == {"id", "faculty", "created_at", "category", "study_year", "booth_id"}
        assert cols("booth_plays") == {"session_id", "booth_id", "date", "attempts"}
        assert not {"device_key", "device_ext_key"} & cols("game_sessions") and "cup_voted" in cols("game_sessions")
        assert [tuple(r) for r in conn.execute("SELECT faculty, category FROM donors_stats ORDER BY id")] == \
            [("W4N", "faktyczny"), ("W4N", "nowy"), ("W3", "nowy")]
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "cup_actual_counts" not in names and "idx_donors_device" not in names
        assert db.get_setting(conn, "device_salt") == "" and db.get_setting(conn, "device_tolerance") == ""
        assert [tuple(r) for r in conn.execute("SELECT name, sort_order FROM partners ORDER BY sort_order")] == [("A", 1), ("B", 2)]
        assert conn.execute("SELECT bonus_attempts FROM game_sessions").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
        conn.close()


def test_dictionary_has_study_years(client):
    d = client.get("/api/dictionary/faculties").json()
    assert len(d["study_years"]) == 8 and d["study_years"][0] == {"code": "I1", "label": "I st., 1. rok"}


def test_pages_have_no_potwierdz_links_and_no_fingerprint(client):
    for url in ("/", "/graj", "/puchar", "/statystyki", "/login", "/dokumenty"):
        text = client.get(url).text
        assert 'href="/potwierdz"' not in text, url
        assert "fingerprint.js" not in text, url
    assert client.get("/static/fingerprint.js").status_code == 404
    page = client.get("/potwierdz").text
    assert "Głos w Pucharze Dawcy PWr" in page and 'id="study-year"' in page
