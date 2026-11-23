import base64
import re
import sqlite3

import pytest

from app import config, db, game
from test_api import JSON, enter, new_session, vote_new, volunteer

TOKEN_RE = re.compile(r"^HG-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG_OK = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>'


def roll(c, booth):
    return c.post("/api/game/roll", json={"booth_id": booth})


def exhaust(c, booth, n=5):
    for _ in range(n):
        assert roll(c, booth).status_code == 200


def always_win(monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)


# --- limit prób na sesję i stanowisko -------------------------------------------
LIMIT_MSG = "Limit prób na tym stanowisku na dziś wykorzystany. Zagraj na innym stanowisku albo wróć jutro."


def test_limit_is_per_session(admin, booth, other_clients):
    a, b = other_clients(), other_clients()
    new_session(a, booth)
    new_session(b, booth)
    exhaust(a, booth)
    r = roll(a, booth)
    assert r.status_code == 429 and r.json()["detail"] == LIMIT_MSG
    assert a.get("/api/game/me").json()["attempts_left"] == 0
    assert b.get("/api/game/me").json()["attempts_left"] == 5  # inna sesja ma własną pulę
    assert roll(b, booth).status_code == 200


def test_limit_is_per_booth_not_across_booths(admin, booth, client):
    """Regulamin konkursu §4.2: 5 prób na dobę na sesję na każdym stanowisku (osobna pula na każdym)."""
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    new_session(client, booth)
    exhaust(client, booth, 3)
    assert client.get("/api/game/me").json()["attempts_left"] == 2
    assert enter(client, "w4").status_code == 200
    assert client.get("/api/game/me").json()["attempts_left"] == 5  # w4 ma własne 5 prób
    exhaust(client, "w4", 5)
    r = roll(client, "w4")
    assert r.status_code == 429 and r.json()["detail"] == LIMIT_MSG
    assert enter(client, booth).status_code == 200
    assert client.get("/api/game/me").json()["attempts_left"] == 2  # pierwsze stoisko pamięta trzy próby
    exhaust(client, booth, 2)
    assert roll(client, booth).status_code == 429
    assert client.get("/api/game/me").json()["attempts_left"] == 0


def test_enter_consent_validation(client, booth):
    new_session(client)
    r = enter(client, booth, consent=False)
    assert r.status_code == 422 and r.json()["detail"] == "Zaakceptuj regulamin i politykę prywatności."
    assert client.post("/api/game/enter", json={"booth_id": booth, "t": "x"}).status_code == 422
    assert roll(client, booth).status_code == 403  # nic nie zapisano


def test_enter_ignores_legacy_device_fields(client, booth):
    """Starszy front mógł jeszcze wysyłać device / device_ext: serwer je ignoruje i nigdzie nie zapisuje."""
    from app import qrtoken
    new_session(client)
    r = client.post("/api/game/enter", json={"booth_id": booth, "t": qrtoken.current(booth), "consent": True,
                                              "device": "ab" * 32, "device_ext": "cd" * 32})
    assert r.status_code == 200
    conn = db.connect()
    dump = "".join(str(tuple(x)) for t in ("game_sessions", "booth_plays", "settings") for x in conn.execute(f"SELECT * FROM {t}"))
    assert "ab" * 32 not in dump and "cd" * 32 not in dump
    assert conn.execute("SELECT consent_at FROM game_sessions").fetchone()[0]
    conn.close()


def test_new_day_resets_pool_without_new_scan(booth, client, monkeypatch):
    new_session(client, booth)
    exhaust(client, booth)
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert roll(client, booth).status_code == 200  # przepustka nadal ważna, pula liczona od nowa dla nowej doby
    assert client.get("/api/game/me").json()["attempts_left"] == 4


def test_no_salt_or_rotation_setting(client):
    conn = db.connect()
    assert db.get_setting(conn, "device_salt") == "" and db.get_setting(conn, "device_tolerance") == ""
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
    assert {"won_token", "consent_at", "cup_voted", "post_bonus_date"} <= cols and "device_key" not in cols
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
    assert b["unranked"] == [{"code": "INNE", "name": "Inne", "registered": 0, "nowy": 0, "zarejestrowany": 0, "faktyczny": 0}]
    assert b["cup_deadline"] == "2026-12-11T15:30:00Z" and b["cup_closed"] is False
    assert client.get("/api/stats/battle").status_code == 404  # stary adres nie istnieje


def test_seed_does_not_overwrite_existing_students(admin):
    put_students(admin, {"W4N": 10})
    db.init_db()
    assert admin.get("/api/admin/students").json()["counts"] == {"W4N": 10}


def test_cup_ranking_unranked_and_inne(admin, booth, client):
    for fac in ["W4N"] * 3 + ["W13"] * 2 + ["W3", "INNE", "W1"]:
        assert vote_new(booth, "nowy", fac).status_code == 200
    # WZ = LD / LS * 100: W4N 3/1000 -> 0.3; W13 2/500 -> 0.4; W3 1/500 -> 0.2 (INNE poza klasyfikacją nawet z liczbą)
    put_students(admin, {"W4N": 1000, "W13": 500, "W3": 500, "INNE": 100, "W2": None})
    b = client.get("/api/stats/cup").json()
    assert b["source"] == "GUS 2026"
    # LD < 10: wszystkie niekwalifikowane, więc bez miejsca
    assert [(r["rank"], r["code"], r["registered"], r["students"], r["wz"], r["qualified"]) for r in b["ranking"]] == \
        [(None, "W13", 2, 500, 0.4, False), (None, "W4N", 3, 1000, 0.3, False), (None, "W3", 1, 500, 0.2, False)]
    assert set(b["ranking"][0]) == {"rank", "code", "name", "registered", "students", "wz", "qualified", "nowy", "zarejestrowany", "faktyczny"}
    codes = [u["code"] for u in b["unranked"]]
    assert len(codes) == 12 and codes[-1] == "INNE" and "W1" in codes and "W4N" not in codes
    assert {"code": "W1", "name": b["unranked"][codes.index("W1")]["name"], "registered": 1,
            "nowy": 1, "zarejestrowany": 0, "faktyczny": 0} in b["unranked"]


def test_cup_rounding_qualification_and_threshold(admin, booth, client):
    """WZ z 3 miejscami; próg LD >= 10: poniżej progu wydział jest za kwalifikowanymi, bez miejsca."""
    add_points("W4N", 20)
    add_points("W13", 10)
    put_students(admin, {"W4N": 6000, "W13": 3000})  # 20/6000 = 0.333; 10/3000 = 0.333
    r = client.get("/api/stats/cup").json()["ranking"]
    assert r[0]["wz"] == 0.333 and r[0]["qualified"] is True and r[0]["rank"] == 1
    add_points("W3", 9)
    put_students(admin, {"W4N": 6000, "W3": 90})  # W3: 9/90 = 10.0, ale LD 9 < 10
    r = client.get("/api/stats/cup").json()["ranking"]
    assert [(x["code"], x["qualified"], x["rank"]) for x in r] == [("W4N", True, 1), ("W3", False, None)]


def test_cup_tie_order_wz_ld_nowy_then_time(admin, booth, client):
    """Remis WZ: wyższe LD, potem więcej „nowy”, potem wcześniejszy czas ostatniego punktu."""
    conn = db.connect()
    conn.executemany("INSERT INTO donors_stats(faculty,created_at,category) VALUES(?,?,?)",
                     [("W4N", "2026-12-09T10:00:00Z", "nowy")] * 20 +
                     [("W13", "2026-12-08T09:00:00Z", "faktyczny")] * 20 +
                     [("W3", "2026-12-08T10:00:00Z", "nowy")] * 20)
    conn.close()
    put_students(admin, {"W4N": 2000, "W13": 2000, "W3": 2000})  # WZ 1.0 każdy, LD 20 każdy
    r = [x["code"] for x in client.get("/api/stats/cup").json()["ranking"]]
    # W4N i W3 mają po 20 „nowy” (W4N później, więc W3 wcześniej); W13 bez „nowy” na końcu
    assert r == ["W3", "W4N", "W13"]


def test_cup_tie_at_three_decimals_decided_by_ld(admin, booth, client):
    """Remis WZ do 3 miejsc: 33/10000 = 0,330 i 10/3030 = 0,330 (po zaokrągleniu); wygrywa wyższe LD."""
    add_points("W13", 33)
    add_points("W3", 10)
    put_students(admin, {"W13": 10000, "W3": 3030})
    r = client.get("/api/stats/cup").json()["ranking"]
    assert [(x["code"], x["wz"]) for x in r] == [("W13", 0.33), ("W3", 0.33)]
    # zero punktów: niekwalifikowany, na końcu
    put_students(admin, {"W13": 10000, "W3": 3030, "W1": 50})
    assert [x["code"] for x in client.get("/api/stats/cup").json()["ranking"]] == ["W13", "W3", "W1"]


def test_students_validation(admin, booth):
    for bad in ({"XX": 5}, {"W4N": 0}, {"W4N": 100001}):
        assert admin.put("/api/admin/students", json={"source": "", "counts": bad}).status_code == 422, bad
    assert admin.put("/api/admin/students", json={"source": "x" * 501, "counts": {}}).status_code == 422
    assert put_students(admin, {"W4N": 100000, "W3": 1}) == {"source": "GUS 2026", "counts": {"W4N": 100000, "W3": 1}}


def test_summary_cup_top3(admin, booth, client):
    """Top3 w podsumowaniu = tylko wydziały kwalifikowane (LD >= 10), nie każdy z punktami."""
    add_points("W4N", 10)
    add_points("W13", 10)
    add_points("W3", 3)  # poniżej progu
    put_students(admin, {})
    assert admin.get("/api/admin/summary?date=all").json()["cup"] == []
    put_students(admin, {"W4N": 100, "W13": 1000, "W3": 10, "W1": 100})  # W4N WZ 10.0, W13 1.0, W3 30.0 (niekwalifikowany)
    top = admin.get("/api/admin/summary?date=all").json()["cup"]
    assert [(r["code"], r["wz"]) for r in top] == [("W4N", 10.0), ("W13", 1.0)]
    assert admin.get("/api/admin/summary?date=2001-01-01").json()["cup"] == []


def test_cup_wz_half_up_rounding(admin, booth, client):
    """10/3200*100 = 0.3125 -> 0.313 (zaokrąglenie połówkami w górę, bez błędu float)."""
    add_points("W4N", 10)
    put_students(admin, {"W4N": 3200})
    assert client.get("/api/stats/cup").json()["ranking"][0]["wz"] == 0.313


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
    assert admin.post("/api/volunteer/cup-qr", json={"category": "nowy"}).status_code == 400
    assert admin.post("/api/auth/booth", json={"booth_id": booth}).json()["booth"]["id"] == booth
    assert admin.post("/api/volunteer/cup-qr", json={"category": "nowy"}).status_code == 200
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
    assert admin.get("/api/admin/settings").json()["facebook_url"] == "https://www.facebook.com/samorzadpwr"
    for bad in ({"facebook_url": "http://fb.com/x"}, {"facebook_url": "javascript:alert(1)"}, {"facebook_url": "https://a b"}):
        assert admin.put("/api/admin/settings", json=bad).status_code == 422, bad
    ok = {"facebook_url": " https://facebook.com/samorzad "}
    assert admin.put("/api/admin/settings", json=ok).json()["facebook_url"] == "https://facebook.com/samorzad"
    assert client.get("/api/config").json()["facebook_url"] == "https://facebook.com/samorzad"
    admin.put("/api/admin/settings", json={"facebook_url": ""})
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


def test_reset_my_game_clears_booth_plays(admin, booth):
    new_session(admin)
    enter(admin, booth)
    roll(admin, booth)
    admin.post("/api/admin/test/reset-my-game", json={})
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM booth_plays").fetchone()[0] == 0
    conn.close()
    assert admin.get("/api/game/me").json()["attempts_left"] == 5
