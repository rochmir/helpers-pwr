import base64
import re
import sqlite3

import pytest

from app import config, db, game
from test_api import DEVICE, JSON, enter, make_code, new_session, register, volunteer

TOKEN_RE = re.compile(r"^HG-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG_OK = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>'


def roll(c, booth):
    return c.post("/api/game/roll", json={"booth_id": booth})


def set_tolerance(admin, n):
    r = admin.put("/api/admin/settings", json={"device_tolerance": n, "facebook_url": ""})
    assert r.status_code == 200, r.text


def exhaust(c, booth, n=5):
    for _ in range(n):
        assert roll(c, booth).status_code == 200


def always_win(monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)


# --- limit prób na urządzenie i hash urządzenia ---------------------------------
def test_limit_five_per_device_same_hash_two_sessions_tolerance_one(admin, booth, other_clients):
    set_tolerance(admin, 1)
    a, b = other_clients(), other_clients()
    new_session(a, booth)
    new_session(b, booth)  # ten sam hash urządzenia w innej przeglądarce
    exhaust(a, booth)
    r = roll(b, booth)
    assert r.status_code == 429 and r.json()["detail"] == "Limit 5 prób na dobę na tym urządzeniu wykorzystany. Wróć jutro."
    assert b.get("/api/game/me").json()["attempts_left"] == 0


def test_tolerance_three_allows_three_sessions(admin, booth, other_clients):
    assert admin.get("/api/admin/settings").json()["device_tolerance"] == 10
    set_tolerance(admin, 3)
    clients = [other_clients() for _ in range(4)]
    for i, c in enumerate(clients):  # ten sam model, różne egzemplarze (różny ext)
        new_session(c)
        assert enter(c, booth, device_ext=f"{i + 1:064x}").status_code == 200
    for c in clients[:3]:
        exhaust(c, booth)
    assert roll(clients[3], booth).status_code == 429
    # inny hash urządzenia ma własną pulę
    other = other_clients()
    new_session(other)
    assert enter(other, booth, device="cd" * 32).status_code == 200
    assert roll(other, booth).status_code == 200


def test_partial_pool_shared_between_sessions(admin, booth, other_clients):
    set_tolerance(admin, 1)
    a, b = other_clients(), other_clients()
    new_session(a, booth)
    new_session(b, booth)
    exhaust(a, booth, 3)
    d = roll(b, booth).json()
    assert d["attempts_left"] == 1
    assert roll(b, booth).status_code == 200 and roll(b, booth).status_code == 429


def test_limit_is_per_device_not_per_booth(admin, booth, client):
    """Regulamin konkursu §4.2: 5 prób na dobę na urządzenie, razem na wszystkich stoiskach."""
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    set_tolerance(admin, 1)
    new_session(client, booth)
    exhaust(client, booth, 3)
    assert enter(client, "w4").status_code == 200
    assert client.get("/api/game/me").json()["attempts_left"] == 2  # trzy próby zeszły z c13
    assert roll(client, "w4").json()["attempts_left"] == 1
    assert roll(client, "w4").status_code == 200
    r = roll(client, "w4")
    assert r.status_code == 429 and r.json()["detail"].startswith("Limit 5 prób na dobę na tym urządzeniu")
    assert enter(client, booth).status_code == 200
    assert roll(client, booth).status_code == 429  # wrócenie na pierwsze stoisko niczego nie odnawia
    assert client.get("/api/game/me").json()["attempts_left"] == 0


def test_limit_across_booths_default_tolerance_and_other_device(admin, booth, other_clients):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    a, b = other_clients(), other_clients()
    new_session(a, booth)
    exhaust(a, booth, 5)
    assert enter(a, "w4").status_code == 200 and roll(a, "w4").status_code == 429
    new_session(b)
    assert enter(b, "w4", device="cd" * 32).status_code == 200  # inne urządzenie ma własną pulę
    assert roll(b, "w4").status_code == 200


def test_enter_consent_and_device_validation(client, booth):
    new_session(client)
    r = enter(client, booth, consent=False)
    assert r.status_code == 422 and r.json()["detail"] == "Zaakceptuj regulamin i politykę prywatności."
    for bad in ("", "ab" * 31, "AB" * 32, "zz" * 32, "ab" * 33):
        assert enter(client, booth, device=bad).status_code == 422, bad
    assert client.post("/api/game/enter", json={"booth_id": booth, "t": "x", "device": DEVICE}).status_code == 422
    assert roll(client, booth).status_code == 403  # nic nie zapisano


def test_device_key_is_hmac_not_raw_hash(booth, client):
    new_session(client, booth)
    conn = db.connect()
    s = conn.execute("SELECT device_key, consent_at FROM game_sessions").fetchone()
    assert re.fullmatch(r"[0-9a-f]{32}", s["device_key"]) and s["consent_at"]
    dump = "".join(str(tuple(r)) for t in ("game_sessions", "booth_plays", "settings")
                   for r in conn.execute(f"SELECT * FROM {t}"))
    assert DEVICE not in dump
    conn.close()


def test_new_day_rotates_salt_and_drops_keys(booth, client, monkeypatch):
    new_session(client, booth)
    exhaust(client, booth, 2)
    conn = db.connect()
    salt1 = db.get_setting(conn, "device_salt")
    key1 = conn.execute("SELECT device_key FROM game_sessions").fetchone()[0]
    assert conn.execute("SELECT SUM(attempts) FROM booth_plays").fetchone()[0] == 2
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    db.rotate_device_salt()  # zadanie w tle, bez żadnego ruchu graczy
    assert db.get_setting(conn, "device_salt") != salt1 and '"2099-01-01"' in db.get_setting(conn, "device_salt")
    assert conn.execute("SELECT device_key FROM game_sessions").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
    assert enter(client, booth).status_code == 200
    key2 = conn.execute("SELECT device_key FROM game_sessions").fetchone()[0]
    assert key2 and key2 != key1  # ten sam hash urządzenia, inny klucz w nowym dniu
    assert roll(client, booth).json()["attempts_left"] == 4
    conn.close()


def test_roll_on_new_day_rotates_before_counting(booth, client, monkeypatch):
    new_session(client, booth)
    exhaust(client, booth)
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert roll(client, booth).status_code == 403  # klucz wyzerowany przez rotację, trzeba zeskanować kod
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
    conn.close()


def test_salt_set_at_startup(client):
    conn = db.connect()
    assert '"date"' in db.get_setting(conn, "device_salt")  # sól powstaje przy starcie, bez żadnego żądania
    conn.close()


# --- trafienia: token i numer ---------------------------------------------------
def test_win_token_and_seq(admin, booth, other_clients, monkeypatch):
    always_win(monkeypatch)
    seen = []
    for n in (1, 2):
        c = other_clients()
        new_session(c, booth)
        d = roll(c, booth).json()
        assert d["win"] is True and TOKEN_RE.match(d["won_token"]) and d["won_seq"] == n
        assert d["won_booth_name"] == "Budynek C-13" and d["won_genotype"] == d["player_genotype"] and d["won_at"]
        me = c.get("/api/game/me").json()
        assert {k: me[k] for k in ("won_token", "won_seq", "won_booth_name", "won_genotype", "won_at")} == \
            {k: d[k] for k in ("won_token", "won_seq", "won_booth_name", "won_genotype", "won_at")}
        seen.append(d["won_token"])
    assert seen[0] != seen[1]
    w = admin.get("/api/admin/wins").json()
    assert w["count"] == 2 and [x["seq"] for x in w["wins"]] == [1, 2]
    assert w["wins"][0] == {"seq": 1, "token": seen[0], "genotype": w["wins"][0]["genotype"], "booth_id": "c13",
                            "booth_name": "Budynek C-13", "won_at": w["wins"][0]["won_at"], "submitted_at": None}


def test_non_win_roll_has_empty_won_fields(booth, client, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    new_session(client, booth)
    d = roll(client, booth).json()
    assert d["won_token"] is None and d["won_seq"] is None and d["won_at"] is None
    assert client.get("/api/game/me").json()["won_token"] is None


def test_test_win_has_seq_zero_and_is_hidden(admin, booth, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    new_session(admin, booth)
    assert admin.post("/api/admin/test/arm-win", json={}).status_code == 200
    d = roll(admin, booth).json()
    assert d["win"] is True and d["won_seq"] == 0 and TOKEN_RE.match(d["won_token"])
    assert admin.post("/api/admin/test/force-win", json={"booth_id": booth}).status_code == 200
    conn = db.connect()
    rows = conn.execute("SELECT seq, is_test, session_id FROM wins ORDER BY rowid").fetchall()
    assert [(r["seq"], r["is_test"]) for r in rows] == [(0, 1), (0, 1)] and all(r["session_id"] is None for r in rows)
    conn.close()
    assert admin.get("/api/admin/wins").json() == {"count": 0, "wins": []}
    # kolejne prawdziwe trafienie dostaje numer 1
    always_win(monkeypatch)
    admin.post("/api/admin/test/reset-my-game", json={})
    assert roll(admin, booth).json()["won_seq"] == 1


def test_reset_my_game_and_wipe_clear_new_tables(admin, booth, monkeypatch):
    always_win(monkeypatch)
    new_session(admin, booth)
    roll(admin, booth)
    admin.post("/api/admin/test/reset-my-game", json={})
    me = admin.get("/api/game/me").json()
    assert me["won_token"] is None and me["attempts_left"] == 5
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM wins").fetchone()[0] == 1  # wpis trafienia zostaje
    assert admin.post("/api/admin/test/wipe", json={"confirm": "USUŃ"}).status_code == 200
    for t in ("wins", "booth_plays"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    conn.close()


def test_wins_require_admin(booth, other_clients):
    assert other_clients().get("/api/admin/wins").status_code == 401
    assert volunteer(other_clients).get("/api/admin/wins").status_code == 403


# --- migracja -------------------------------------------------------------------
def test_migration_backfills_wins_and_drops_raffle(booth, client):
    conn = db.connect()
    conn.execute("CREATE TABLE raffle_draws(id INTEGER PRIMARY KEY, genotype TEXT, drawn_at TEXT)")
    for g, at, test in (("0000000001", "2026-10-26T10:00:00Z", 0), ("0000000002", "2026-10-26T09:00:00Z", 1),
                        ("0000000003", "2026-10-26T11:00:00Z", 0)):
        conn.execute("INSERT INTO genotype_history(genotype,booth_id,created_at,matched_at,is_test) VALUES(?,?,?,?,?)",
                     (g, "c13", at, at, test))
    conn.execute("INSERT INTO game_sessions(session_id,created_at,has_won,won_genotype,won_at) "
                 "VALUES('s1','2026-10-26T10:00:00Z',1,'0000000003','2026-10-26T11:00:00Z')")
    for _ in range(2):  # idempotentnie
        db.init_db()
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='raffle_draws'").fetchone() is None
        rows = conn.execute("SELECT genotype, seq, is_test, session_id, token FROM wins ORDER BY won_at").fetchall()
        assert [(r["genotype"], r["seq"], r["is_test"], r["session_id"]) for r in rows] == \
            [("0000000002", 0, 1, None), ("0000000001", 1, 0, None), ("0000000003", 2, 0, None)]  # wpis wygranej bez sesji (§4.3)
        assert all(TOKEN_RE.match(r["token"]) for r in rows)
        assert conn.execute("SELECT won_token FROM game_sessions").fetchone()[0] == rows[2]["token"]
    conn.close()


def test_migration_adds_columns_to_old_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.executescript("CREATE TABLE game_sessions(session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                      "has_won INTEGER NOT NULL DEFAULT 0);"
                      "CREATE TABLE volunteers(login TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);"
                      "INSERT INTO volunteers VALUES('ania','x','2026-10-26T00:00:00Z');")
    raw.commit()
    raw.close()
    db.init_db()
    conn = db.connect()
    assert conn.execute("SELECT role FROM volunteers").fetchone()[0] == "volunteer"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(game_sessions)")}
    assert {"won_token", "consent_at", "device_key"} <= cols
    conn.close()


# --- Puchar Dawcy PWr: Wskaźnik Zaangażowania -----------------------------------
def put_students(admin, counts, source="GUS 2026"):
    r = admin.put("/api/admin/students", json={"source": source, "counts": counts})
    assert r.status_code == 200, r.text
    return r.json()


def add_points(code, n, day_iso="2026-12-08T10:00:00Z"):
    conn = db.connect()
    conn.executemany("INSERT INTO donors_stats(faculty,created_at) VALUES(?,?)", [(code, day_iso)] * n)
    conn.close()


def test_cup_seed_ranks_all_faculties_except_other(admin, booth, client):
    assert admin.get("/api/admin/students").json()["counts"]["W4N"] == 4576
    b = client.get("/api/stats/cup").json()
    assert "Sprawozdanie Rektora" in b["source"] and len(b["ranking"]) == 14
    assert b["unranked"] == [{"code": "INNE", "name": "Inne", "registered": 0, "actual": 0, "potential": 0}]
    assert b["cup_deadline"] == "2026-12-11T15:30:00Z" and b["cup_closed"] is False
    assert client.get("/api/stats/battle").status_code == 404  # stary adres nie istnieje


def test_seed_does_not_overwrite_existing_students(admin):
    put_students(admin, {"W4N": 10})
    db.init_db()
    assert admin.get("/api/admin/students").json()["counts"] == {"W4N": 10}


def test_cup_ranking_unranked_and_inne(admin, booth, client):
    for fac in ["W4N"] * 3 + ["W13"] * 2 + ["W3", "INNE", "W1"]:
        assert register(client, make_code(admin, booth_id=booth), fac).status_code == 200
    # WZ = LD / LS * 100: W4N 3/1000 -> 0.3; W13 2/500 -> 0.4; W3 1/500 -> 0.2 (INNE poza klasyfikacją nawet z liczbą)
    put_students(admin, {"W4N": 1000, "W13": 500, "W3": 500, "INNE": 100, "W2": None})
    b = client.get("/api/stats/cup").json()
    assert b["source"] == "GUS 2026"
    assert [(r["rank"], r["code"], r["registered"], r["students"], r["wz"]) for r in b["ranking"]] == \
        [(1, "W13", 2, 500, 0.4), (2, "W4N", 3, 1000, 0.3), (3, "W3", 1, 500, 0.2)]
    assert set(b["ranking"][0]) == {"rank", "code", "name", "registered", "students", "wz", "actual", "potential"}
    codes = [u["code"] for u in b["unranked"]]
    assert len(codes) == 12 and codes[-1] == "INNE" and "W1" in codes and "W4N" not in codes
    assert {"code": "W1", "name": b["unranked"][codes.index("W1")]["name"], "registered": 1,
            "actual": 0, "potential": 1} in b["unranked"]


def test_cup_rounding_and_ties(admin, booth, client):
    for fac in ["W4N"] * 2 + ["W13"] + ["W3"]:
        register(client, make_code(admin, booth_id=booth), fac)
    put_students(admin, {"W4N": 600, "W13": 300, "W3": 300})  # 0.33, 0.33, 0.33
    r = client.get("/api/stats/cup").json()["ranking"]
    assert r[0]["wz"] == 0.33
    # remis: więcej punktów (LD), potem kolejność słownika (W3 przed W13)
    assert [x["code"] for x in r] == ["W4N", "W3", "W13"]


def test_cup_tie_at_two_decimals_decided_by_ld_not_raw_ratio(admin, booth, client):
    """§4.4: remis liczony „do drugiego miejsca po przecinku”: 33/10000 i 1/300 to oba 0,33, więc wygrywa wyższe LD."""
    add_points("W13", 33)
    add_points("W3", 1)
    put_students(admin, {"W13": 10000, "W3": 300})
    r = client.get("/api/stats/cup").json()["ranking"]
    assert [(x["code"], x["wz"]) for x in r] == [("W13", 0.33), ("W3", 0.33)]
    # i zero punktów też jest sklasyfikowane (WZ 0), ale pod punktowanymi
    put_students(admin, {"W13": 10000, "W3": 300, "W1": 50})
    assert [x["code"] for x in client.get("/api/stats/cup").json()["ranking"]] == ["W13", "W3", "W1"]


def test_students_validation(admin, booth):
    for bad in ({"XX": 5}, {"W4N": 0}, {"W4N": 100001}):
        assert admin.put("/api/admin/students", json={"source": "", "counts": bad}).status_code == 422, bad
    assert admin.put("/api/admin/students", json={"source": "x" * 501, "counts": {}}).status_code == 422
    assert put_students(admin, {"W4N": 100000, "W3": 1}) == {"source": "GUS 2026", "counts": {"W4N": 100000, "W3": 1}}


def test_summary_cup_top3(admin, booth, client):
    for fac in ["W4N"] * 3 + ["W13", "W3"]:
        register(client, make_code(admin, booth_id=booth), fac)
    put_students(admin, {})
    assert admin.get("/api/admin/summary?date=all").json()["cup"] == []
    put_students(admin, {"W4N": 300, "W13": 100, "W3": 100, "W1": 100})
    top = admin.get("/api/admin/summary?date=all").json()["cup"]
    assert [(r["code"], r["wz"]) for r in top] == [("W4N", 1.0), ("W3", 1.0), ("W13", 1.0)]
    assert admin.get("/api/admin/summary?date=2001-01-01").json()["cup"] == []


def test_cup_day_filter_uses_warsaw_day(admin, booth, client):
    """Doba Europe/Warsaw, nie UTC: 23:30 UTC 10 grudnia to już 11 grudnia o 00:30 w Warszawie."""
    add_points("W4N", 2, "2026-12-10T23:30:00Z")
    add_points("W4N", 1, "2026-12-10T22:30:00Z")
    assert admin.get("/api/admin/summary?date=2026-12-11").json()["registered"] == 2
    assert admin.get("/api/admin/summary?date=2026-12-10").json()["registered"] == 1
    assert admin.get("/api/admin/days").json()[:2] == ["2026-12-11", "2026-12-10"]


# --- logowanie i rangi ----------------------------------------------------------
def test_login_roles_and_me(admin, booth, other_clients):
    v = volunteer(other_clients)
    assert v.get("/api/auth/me").json() == {"login": "tester", "role": "volunteer",
                                            "booth": {"id": "c13", "name": "Budynek C-13"}}
    assert admin.post("/api/admin/volunteers", json={"login": "szef", "password": "tajne-haslo2", "role": "admin"}).json()["role"] == "admin"
    boss = other_clients()
    assert boss.post("/api/auth/login", json={"login": "szef", "password": "tajne-haslo2"}).json()["role"] == "admin"
    assert boss.get("/api/admin/booths").status_code == 200
    roles = {x["login"]: x["role"] for x in admin.get("/api/admin/volunteers").json()}
    assert roles == {"szef": "admin", "tester": "volunteer"}


def test_admin_can_pick_booth_and_act_on_it(admin, booth):
    assert admin.post("/api/volunteer/generate-code", json={}).status_code == 400
    assert admin.post("/api/auth/booth", json={"booth_id": booth}).json()["booth"]["id"] == booth
    assert admin.post("/api/volunteer/generate-code", json={}).status_code == 200
    assert admin.get("/api/volunteer/me").json()["booth"]["id"] == booth


def test_reserved_admin_login_and_invalid_role(admin):
    assert admin.post("/api/admin/volunteers", json={"login": "admin"}).status_code == 422
    assert admin.post("/api/admin/volunteers", json={"login": "ktos", "role": "szef"}).status_code == 422


def test_role_change_applies_immediately(admin, booth, other_clients):
    admin.post("/api/admin/volunteers", json={"login": "szef", "password": "tajne-haslo2", "role": "admin"})
    boss = other_clients()
    boss.post("/api/auth/login", json={"login": "szef", "password": "tajne-haslo2"})
    assert boss.get("/api/admin/volunteers").status_code == 200
    assert admin.patch("/api/admin/volunteers/szef", json={"role": "volunteer"}).json() == {"login": "szef", "role": "volunteer"}
    assert boss.get("/api/admin/volunteers").status_code == 403  # degradacja od razu, bez ponownego logowania
    assert boss.get("/api/auth/me").json()["role"] == "volunteer"
    assert admin.patch("/api/admin/volunteers/szef", json={"role": "admin"}).status_code == 200
    assert boss.get("/api/admin/volunteers").status_code == 200  # awans też
    assert admin.patch("/api/admin/volunteers/szef", json={"role": "x"}).status_code == 422
    assert admin.patch("/api/admin/volunteers/nikt", json={"role": "admin"}).status_code == 404


def test_emergency_admin_invalid_after_secret_change(admin, monkeypatch):
    assert admin.get("/api/admin/booths").status_code == 200
    monkeypatch.setenv("ADMIN_SECRET", "inny-sekret")
    assert admin.get("/api/admin/booths").status_code == 401


def test_old_panels_redirect_to_login(client):
    for path in ("/admin", "/wolontariusz"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/login"


# --- ustawienia, strony ---------------------------------------------------------
def test_settings_and_facebook_in_config(admin, client):
    assert admin.get("/api/admin/settings").json() == {"device_tolerance": 10, "facebook_url": "https://www.facebook.com/samorzadpwr",
                                                       "device_stats": {"date": config.today(), "base_keys": 0, "ext_keys": 0}}
    for bad in ({"device_tolerance": 0}, {"device_tolerance": 51}, {"device_tolerance": 3, "facebook_url": "http://fb.com/x"},
                {"device_tolerance": 3, "facebook_url": "javascript:alert(1)"}, {"device_tolerance": 3, "facebook_url": "https://a b"}):
        assert admin.put("/api/admin/settings", json=bad).status_code == 422, bad
    ok = {"device_tolerance": 7, "facebook_url": " https://facebook.com/samorzad "}
    assert admin.put("/api/admin/settings", json=ok).json()["facebook_url"] == "https://facebook.com/samorzad"
    assert client.get("/api/config").json()["facebook_url"] == "https://facebook.com/samorzad"
    admin.put("/api/admin/settings", json={"device_tolerance": 7, "facebook_url": ""})
    assert client.get("/api/config").json()["facebook_url"] is None
    db.init_db()  # domyślny profil z seedu wraca tylko raz: wyczyszczony adres zostaje pusty
    assert client.get("/api/config").json()["facebook_url"] is None


# --- partnerzy ------------------------------------------------------------------
def upload(c, raw, name="Partner", filename="logo.png"):
    data = raw if isinstance(raw, bytes) else raw.encode()
    return c.post("/api/admin/partners", json={"name": name, "filename": filename,
                                               "data_base64": base64.b64encode(data).decode()})


def test_partner_upload_serve_delete(admin, other_clients):
    client = other_clients()  # anonimowo
    assert client.get("/api/partners").json() == []
    r = upload(admin, PNG, filename="../../etc/passwd.png")  # nazwa klienta jest ignorowana
    assert r.status_code == 201
    d = r.json()
    assert re.fullmatch(r"/partners/[0-9a-f]{32}\.png", d["url"]) and d["name"] == "Partner"
    assert client.get("/api/partners").json() == [d]
    f = client.get(d["url"])
    assert f.status_code == 200 and f.content == PNG and f.headers["content-type"] == "image/png"
    assert client.delete(f"/api/admin/partners/{d['id']}", headers=JSON).status_code == 401
    assert admin.delete(f"/api/admin/partners/{d['id']}", headers=JSON).json() == {"ok": True}
    assert client.get(d["url"]).status_code == 404 and client.get("/api/partners").json() == []
    assert admin.delete(f"/api/admin/partners/{d['id']}", headers=JSON).status_code == 404


def test_partner_types_by_signature(admin, client):
    cases = {"jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 20, "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ", "svg": SVG_OK}
    for ext, raw in cases.items():
        r = upload(admin, raw, filename="x.png")
        assert r.status_code == 201 and r.json()["url"].endswith("." + ext), ext
    assert client.get(r.json()["url"]).headers["content-type"] == "image/svg+xml"


def test_partner_rejects_bad_signature_and_size(admin):
    assert upload(admin, b"GIF89a....", filename="x.png").status_code == 422  # rozszerzenie nie decyduje
    assert upload(admin, b"").status_code == 422
    assert upload(admin, PNG + b"\x00" * 1_500_000).status_code == 422
    assert upload(admin, "<html><svg></svg></html>").status_code == 422
    r = admin.post("/api/admin/partners", json={"name": "x", "filename": "x.png", "data_base64": "!!nie-base64!!"})
    assert r.status_code == 422
    assert upload(admin, PNG, name="  ").status_code == 422


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" onload="alert(1)"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect onclick="x()" width="1" height="1"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><foreignObject><p/></foreignObject></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1" height="1">'
    '<image xlink:href="https://evil.example/a.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><a href="javascript:alert(1)"><rect/></a></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><style>@import url(//evil.example/x.css);</style></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect style="fill:url(https://evil.example/x)"/></svg>',
    '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" height="1"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect',
])
def test_partner_rejects_dangerous_svg(admin, svg):
    assert upload(admin, svg, filename="x.svg").status_code == 422


def test_partner_svg_internal_href_allowed(admin):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><defs><rect id="a" width="1" height="1"/></defs>'
           '<use href="#a"/></svg>')
    assert upload(admin, svg).status_code == 201


def test_partner_file_route_blocks_traversal_and_foreign_names(admin, client, tmp_path):
    from app.routes import partners
    (partners.partners_dir().parent / "secret.png").write_bytes(PNG)
    (partners.partners_dir() / "plain.png").write_bytes(PNG)
    for name in ("..%2Fsecret.png", "%2e%2e%2fsecret.png", "plain.png", "A" * 32 + ".png", "0" * 32 + ".gif",
                 "0" * 32 + ".png", "0" * 32 + ".png/x", "0" * 31 + ".png"):
        assert client.get(f"/partners/{name}").status_code == 404, name


def test_partner_admin_only(booth, other_clients):
    v = volunteer(other_clients)
    assert upload(v, PNG).status_code == 403
    assert upload(other_clients(), PNG).status_code == 401


# --- iteracja 5: klucz rozszerzony ----------------------------------------------
EXT_A = "a1" * 32
EXT_B = "b2" * 32


def test_same_ext_two_sessions_share_five_despite_high_tolerance(admin, booth, other_clients):
    set_tolerance(admin, 50)
    a, b = other_clients(), other_clients()
    for c in (a, b):
        new_session(c)
        assert enter(c, booth, device_ext=EXT_A).status_code == 200
    exhaust(a, booth, 3)
    assert roll(b, booth).json()["attempts_left"] == 1
    assert roll(b, booth).status_code == 200 and roll(b, booth).status_code == 429


def test_same_device_different_ext_each_has_five_up_to_ceiling(admin, booth, other_clients):
    set_tolerance(admin, 2)  # sufit 10 prób na klucz podstawowy
    cs = [other_clients() for _ in range(3)]
    for c, ext in zip(cs, (EXT_A, EXT_B, "c3" * 32)):
        new_session(c)
        assert enter(c, booth, device_ext=ext).status_code == 200
    exhaust(cs[0], booth)
    exhaust(cs[1], booth)
    assert roll(cs[0], booth).status_code == 429 and roll(cs[1], booth).status_code == 429
    assert roll(cs[2], booth).status_code == 429  # sufit 5*2 osiągnięty
    assert cs[2].get("/api/game/me").json()["attempts_left"] == 0


def test_tolerance_one_is_five_total_per_device(admin, booth, other_clients):
    set_tolerance(admin, 1)
    a, b = other_clients(), other_clients()
    for c, ext in ((a, EXT_A), (b, EXT_B)):
        new_session(c)
        assert enter(c, booth, device_ext=ext).status_code == 200
    exhaust(a, booth, 3)
    assert roll(b, booth).json()["attempts_left"] == 1
    assert roll(b, booth).status_code == 200 and roll(b, booth).status_code == 429


def test_missing_device_ext_works_and_invalid_is_422(booth, client):
    new_session(client, booth)
    assert roll(client, booth).status_code == 200
    conn = db.connect()
    assert conn.execute("SELECT ext_key FROM booth_plays").fetchone()[0] == \
        conn.execute("SELECT device_ext_key FROM game_sessions").fetchone()[0]
    conn.close()
    for bad in ("", "ab" * 31, "ZZ" * 32):
        assert enter(client, booth, device_ext=bad).status_code == 422, bad


def test_ext_key_is_hmac_and_differs_from_base(booth, client):
    new_session(client)
    assert enter(client, booth, device_ext=EXT_A).status_code == 200
    conn = db.connect()
    s = conn.execute("SELECT device_key, device_ext_key FROM game_sessions").fetchone()
    assert re.fullmatch(r"[0-9a-f]{32}", s["device_ext_key"]) and s["device_ext_key"] != s["device_key"]
    dump = "".join(str(tuple(r)) for t in ("game_sessions", "booth_plays", "settings") for r in conn.execute(f"SELECT * FROM {t}"))
    assert EXT_A not in dump
    conn.close()


def test_rotation_clears_both_keys(booth, client, monkeypatch):
    new_session(client)
    enter(client, booth, device_ext=EXT_A)
    conn = db.connect()
    assert conn.execute("SELECT device_ext_key FROM game_sessions").fetchone()[0]
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    db.rotate_device_salt()
    s = conn.execute("SELECT device_key, device_ext_key FROM game_sessions").fetchone()
    assert s["device_key"] is None and s["device_ext_key"] is None
    conn.close()


def test_device_stats(admin, booth, other_clients):
    a, b, c = other_clients(), other_clients(), other_clients()
    for cl, dev, ext in ((a, DEVICE, EXT_A), (b, DEVICE, EXT_B), (c, "cd" * 32, "c3" * 32)):
        new_session(cl)
        assert enter(cl, booth, device=dev, device_ext=ext).status_code == 200
        roll(cl, booth)
    st = admin.get("/api/admin/settings").json()["device_stats"]
    assert st == {"date": config.today(), "base_keys": 2, "ext_keys": 3}
    assert admin.put("/api/admin/settings", json={"device_tolerance": 4, "facebook_url": ""}).json()["device_stats"] == st


def test_tolerance_range_1_to_50(admin):
    for n in (1, 50):
        set_tolerance(admin, n)
        assert admin.get("/api/admin/settings").json()["device_tolerance"] == n
    for n in (0, 51):
        assert admin.put("/api/admin/settings", json={"device_tolerance": n, "facebook_url": ""}).status_code == 422


def test_reset_my_game_clears_ext_plays(admin, booth):
    new_session(admin)
    enter(admin, booth, device_ext=EXT_A)
    roll(admin, booth)
    admin.post("/api/admin/test/reset-my-game", json={})
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
    conn.close()
    assert admin.get("/api/game/me").json()["attempts_left"] == 5
