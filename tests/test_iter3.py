"""Iteracja 3: najlepszy wynik dnia, bonus za rejestrację, kod QR co minutę, konta wolontariuszy, słownik z „Inne”."""
import random
import sqlite3
from datetime import timedelta

from app import config, db, game, qrtoken

from test_api import JSON, enter, make_code, new_session, register, volunteer


def force_matches(monkeypatch, seq):
    """Kolejne zwykłe rzuty dają zadane liczby zgodnych pozycji."""
    it = iter(seq)
    rng = random.Random(1)
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    monkeypatch.setattr(game, "roll", lambda target, rng_=None: (lambda k: (k, game.make_match(target, k, rng)))(next(it)))


def roll(c, booth):
    return c.post("/api/game/roll", json={"booth_id": booth})


def set_clock(monkeypatch, dt):
    monkeypatch.setattr(config, "now", lambda: dt)


def test_win_odds_constant():
    assert game.WIN_ONE_IN == 300


# --- najlepszy wynik dnia -------------------------------------------------------
def test_best_today(client, booth, monkeypatch):
    force_matches(monkeypatch, [6, 8, 5, 7, 5])
    new_session(client, booth)
    assert client.get("/api/game/me").json()["best_today"] == 0
    got = [roll(client, booth).json() for _ in range(5)]
    assert [g["best_today"] for g in got] == [6, 8, 8, 8, 8]
    assert got[-1]["attempts_left"] == 0
    assert client.get("/api/game/me").json()["best_today"] == 8
    r = roll(client, booth)
    assert r.status_code == 429 and r.json()["best_today"] == 8
    assert client.post("/api/game/session", json={}).json()["best_today"] == 8


def test_best_today_win_is_ten_and_resets_next_day(client, booth, monkeypatch):
    new_session(client, booth)
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    assert roll(client, booth).json()["best_today"] == 10
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert client.get("/api/game/me").json()["best_today"] == 0


# --- bonus za rejestrację -------------------------------------------------------
def test_register_bonus_with_session(admin, booth, other_clients):
    p = other_clients()
    new_session(p)
    d = register(p, make_code(admin, booth_id=booth)).json()
    assert d["bonus_attempts_granted"] == 10 and d["attempts_left"] == 15 and d["token"]
    assert d["play_path"].startswith("/graj?stoisko=c13&t=") and qrtoken.valid("c13", d["play_path"].split("t=")[1])
    me = p.get("/api/game/me").json()
    assert me["attempts_left"] == 15 and me["bonus_attempts"] == 10
    # sumuje się: drugi kod = kolejne +10
    assert register(p, make_code(admin, booth_id=booth)).json()["attempts_left"] == 25


def test_register_bonus_without_session_creates_one(admin, booth, other_clients):
    p = other_clients()
    r = register(p, make_code(admin, booth_id=booth))
    d = r.json()
    assert d["attempts_left"] == 15 and d["token"] and "hp_game" in r.headers["set-cookie"]
    assert p.get("/api/game/me").json()["bonus_attempts"] == 10  # cookie ustawione
    # token z odpowiedzi działa jako nagłówek
    q = other_clients()
    assert q.get("/api/game/me", headers={"X-Game-Token": d["token"]}).json()["attempts_left"] == 15


def test_failed_register_gives_no_bonus(admin, booth, other_clients):
    p = other_clients()
    new_session(p)
    assert register(p, "C13-ZZZZ").status_code == 404
    assert register(p, make_code(admin, booth_id=booth), faculty="XX").status_code == 422
    assert p.get("/api/game/me").json()["attempts_left"] == 5


def test_daily_pool_used_before_bonus_and_bonus_survives_midnight(admin, booth, other_clients, monkeypatch):
    p = other_clients()
    new_session(p, booth)
    register(p, make_code(admin, booth_id=booth))  # 5 dziennych + 10 bonusu
    for i in range(5):
        d = roll(p, booth).json()
        assert d["bonus_attempts"] == 10 and d["attempts_left"] == 14 - i  # dzienne schodzą pierwsze
    d = roll(p, booth).json()
    assert d["bonus_attempts"] == 9 and d["attempts_left"] == 9
    # kolejny dzień: znowu 5 dziennych + 9 bonusu (bonus nie wygasa)
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    me = p.get("/api/game/me").json()
    assert me["attempts_left"] == 14 and me["bonus_attempts"] == 9 and me["best_today"] == 0
    # wyczerpanie wszystkiego
    for _ in range(14):
        assert roll(p, booth).status_code == 200
    r = roll(p, booth)
    assert r.status_code == 429 and r.json()["attempts_left"] == 0
    assert p.get("/api/game/me").json()["bonus_attempts"] == 0


def test_best_today_counts_bonus_rolls(admin, booth, other_clients, monkeypatch):
    force_matches(monkeypatch, [5] * 5 + [9])
    p = other_clients()
    new_session(p, booth)
    register(p, make_code(admin, booth_id=booth))
    for _ in range(5):
        roll(p, booth)
    assert roll(p, booth).json()["best_today"] == 9  # próba z puli bonusowej też liczy się do rekordu


# --- kod QR i przepustka --------------------------------------------------------
def test_qr_token_validity_window(booth, monkeypatch):
    t0 = config.now().replace(second=30, microsecond=0)
    set_clock(monkeypatch, t0)
    tok = qrtoken.current(booth)
    assert len(tok) == 10 and tok.isalnum()
    assert qrtoken.valid(booth, tok)
    set_clock(monkeypatch, t0 + timedelta(seconds=40))  # kolejna minuta: token inny, stary jeszcze ważny
    assert qrtoken.current(booth) != tok and qrtoken.valid(booth, tok)
    set_clock(monkeypatch, t0 + timedelta(minutes=2))   # 2 minuty później: nadal ważny
    assert qrtoken.valid(booth, tok)
    set_clock(monkeypatch, t0 + timedelta(minutes=3))   # starszy niż 2 minuty wstecz
    assert not qrtoken.valid(booth, tok)
    set_clock(monkeypatch, t0)
    assert not qrtoken.valid("inne", tok) and not qrtoken.valid(booth, "") and not qrtoken.valid(booth, None)
    assert not qrtoken.valid(booth, tok[:-1] + ("a" if tok[-1] != "a" else "b"))


def test_roll_requires_pass(client, booth):
    new_session(client)
    r = roll(client, booth)
    assert r.status_code == 403 and r.json()["detail"] == "Zeskanuj ponownie kod QR ze stoiska."
    assert enter(client, booth, "zlytoken00").status_code == 403
    assert enter(client, "nope").status_code == 404
    assert roll(client, booth).status_code == 403
    assert enter(client, booth).status_code == 200
    assert roll(client, booth).status_code == 200
    assert client.get("/api/booth/c13/state").json()["rolls_count"] == 1


def test_enter_requires_session(client, booth):
    assert enter(client, booth).status_code == 401


def test_pass_is_per_booth_and_expires(client, booth, monkeypatch):
    client.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    new_session(client, booth)
    assert roll(client, "w4").status_code == 403  # przepustka dotyczy stoiska c13
    t0 = config.now()
    set_clock(monkeypatch, t0 + timedelta(minutes=config.PASS_MINUTES - 1))
    assert roll(client, booth).status_code == 200
    set_clock(monkeypatch, t0 + timedelta(minutes=config.PASS_MINUTES + 1))
    assert roll(client, booth).status_code == 403
    assert client.get("/api/game/me").json()["pass_booth"] is None
    # ponowne skanowanie (świeży token) odnawia przepustkę
    assert enter(client, booth).status_code == 200
    assert roll(client, booth).status_code == 200
    assert client.get("/api/game/me").json()["pass_booth"] == booth


def test_expired_qr_token_rejected_at_enter(client, booth, monkeypatch):
    new_session(client)
    old = qrtoken.current(booth)
    set_clock(monkeypatch, config.now() + timedelta(minutes=5))
    r = enter(client, booth, old)
    assert r.status_code == 403 and "Zeskanuj ponownie" in r.json()["detail"]


def test_exhausted_player_gets_429_not_403(client, booth, monkeypatch):
    new_session(client, booth)
    for _ in range(5):
        roll(client, booth)
    set_clock(monkeypatch, config.now() + timedelta(minutes=config.PASS_MINUTES + 5))
    assert roll(client, booth).status_code == 429


def test_booth_state_play_path_only_for_staff(admin, booth, other_clients):
    anon = other_clients()
    st = anon.get(f"/api/booth/{booth}/state").json()
    assert st["play_path"] is None and st["genotype"] and st["name"] == "Budynek C-13"
    assert "t=" not in str(st)
    # wolontariusz tego stoiska
    v = volunteer(other_clients)
    p = v.get(f"/api/booth/{booth}/state").json()
    assert p["play_path"] == f"/graj?stoisko=c13&t={qrtoken.current('c13')}" and 1 <= p["qr_seconds_left"] <= 60
    # wolontariusz zalogowany na inne stoisko
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    assert v.get("/api/booth/w4/state").json()["play_path"] is None
    # admin widzi każde
    assert admin.get("/api/booth/w4/state").json()["play_path"].startswith("/graj?stoisko=w4&t=")
    # link ze stanu naprawdę wpuszcza do gry
    g = other_clients()
    new_session(g)
    t = p["play_path"].split("t=")[1]
    assert enter(g, booth, t).status_code == 200


def test_old_pin_cookie_session_no_longer_valid(booth, other_clients):
    """Cookie z czasów logowania PIN-em (bez loginu) nie daje dostępu."""
    from app import auth
    v = other_clients()
    v.cookies.set(auth.STAFF_COOKIE, auth._staff_serializer().dumps({"role": "volunteer", "booth": "c13", "ph": "abcdefgh"}))
    assert v.get("/api/volunteer/me").status_code == 401


# --- konta wolontariuszy --------------------------------------------------------
def test_volunteer_account_lifecycle(admin, booth, other_clients):
    r = admin.post("/api/admin/volunteers", json={"login": "Ania-C13"})  # bez hasła: generowane, login do małych liter
    assert r.status_code == 201
    d = r.json()
    assert d["login"] == "ania-c13" and len(d["password"]) == 12
    assert not set(d["password"]) & set("0O1lI")
    lst = admin.get("/api/admin/volunteers").json()
    assert [x["login"] for x in lst] == ["ania-c13", "tester"] and all(set(x) == {"login", "created_at"} for x in lst)
    assert d["password"] not in str(lst)
    v = volunteer(other_clients, login="ania-c13", password=d["password"])
    assert v.get("/api/volunteer/me").status_code == 200
    # hasło własne
    assert admin.post("/api/admin/volunteers", json={"login": "bartek.k", "password": "dlugie-haslo-1"}).json()["password"] == "dlugie-haslo-1"
    assert admin.post("/api/admin/volunteers", json={"login": "ania-c13"}).status_code == 409


def test_volunteer_account_validation(admin):
    for bad in ("ab", "a" * 33, "ania c13", "ania!", "Zażółć", "", "  "):
        assert admin.post("/api/admin/volunteers", json={"login": bad}).status_code == 422, bad
    assert admin.post("/api/admin/volunteers", json={"login": "okok", "password": "krotkie"}).status_code == 422
    assert admin.post("/api/admin/volunteers", json={"login": "a.b_c-1"}).status_code == 201


def test_reset_password_invalidates_session(admin, booth, other_clients):
    v = volunteer(other_clients)
    assert v.get("/api/volunteer/me").status_code == 200
    r = admin.post("/api/admin/volunteers/tester/reset-password", json={})
    assert r.status_code == 200 and len(r.json()["password"]) == 12
    assert v.get("/api/volunteer/me").status_code == 401
    other = other_clients()
    assert other.post("/api/volunteer/auth", json={"login": "tester", "password": "tajne-haslo1", "booth_id": booth}).status_code == 401
    assert volunteer(other_clients, password=r.json()["password"]).get("/api/volunteer/me").status_code == 200
    assert admin.post("/api/admin/volunteers/tester/reset-password", json={"password": "x"}).status_code == 422
    assert admin.post("/api/admin/volunteers/nikt/reset-password", json={}).status_code == 404


def test_delete_volunteer_invalidates_session(admin, booth, other_clients):
    v = volunteer(other_clients)
    assert admin.delete("/api/admin/volunteers/tester", headers=JSON).status_code == 200
    assert v.get("/api/volunteer/me").status_code == 401
    assert admin.delete("/api/admin/volunteers/tester", headers=JSON).status_code == 404
    assert admin.get("/api/admin/volunteers").json() == []


def test_volunteer_cannot_manage_accounts(booth, other_clients):
    v = volunteer(other_clients)
    assert v.get("/api/admin/volunteers").status_code == 403
    assert v.post("/api/admin/volunteers", json={"login": "hacker"}).status_code == 403
    assert v.post("/api/admin/volunteers/tester/reset-password", json={}).status_code == 403
    assert v.delete("/api/admin/volunteers/tester", headers=JSON).status_code == 403
    assert other_clients().get("/api/admin/volunteers").status_code == 401


def test_public_booth_list(booth, other_clients):
    assert other_clients().get("/api/booths").json() == [{"id": "c13", "name": "Budynek C-13"}]


def test_password_hash_not_plaintext(admin, booth):
    conn = db.connect()
    h = conn.execute("SELECT password_hash FROM volunteers WHERE login='tester'").fetchone()[0]
    conn.close()
    assert h.startswith("$argon2") and "tajne-haslo1" not in h


# --- słownik z „Inne” -----------------------------------------------------------
def test_dictionary_ends_with_other(admin, booth, client):
    facs = client.get("/api/dictionary/faculties").json()["faculties"]
    assert facs[-1] == {"code": "INNE", "name": "Inne"}
    assert [f["code"] for f in facs].index("W2") < [f["code"] for f in facs].index("W10") if "W10" in [f["code"] for f in facs] else True
    # INNE przesunięte w środek wraca na koniec; brakujące jest dopisywane
    mixed = [facs[-1]] + facs[:-1]
    assert admin.put("/api/admin/dictionary", json={"faculties": mixed}).status_code == 200
    assert admin.get("/api/admin/dictionary").json()["faculties"][-1]["code"] == "INNE"
    without = [f for f in facs if f["code"] != "INNE"]
    assert admin.put("/api/admin/dictionary", json={"faculties": without}).status_code == 200
    assert admin.get("/api/admin/dictionary").json()["faculties"][-1] == {"code": "INNE", "name": "Inne"}
    assert register(client, make_code(admin, booth_id=booth), faculty="INNE").status_code == 200


# --- migracja bazy z iteracji 2 -------------------------------------------------
ITER2_SCHEMA = """
CREATE TABLE booths(id TEXT PRIMARY KEY CHECK(id GLOB '[a-z0-9]*'), name TEXT NOT NULL, pin_hash TEXT NOT NULL,
  current_genotype TEXT NOT NULL, genotype_updated_at TEXT NOT NULL, matches_count INTEGER NOT NULL DEFAULT 0,
  rolls_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE genotype_history(genotype TEXT PRIMARY KEY, booth_id TEXT NOT NULL, created_at TEXT NOT NULL, matched_at TEXT NULL);
CREATE TABLE game_sessions(session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, has_won INTEGER NOT NULL DEFAULT 0);
CREATE TABLE game_attempts(session_id TEXT, date TEXT, attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, date));
CREATE TABLE registration_codes(code TEXT PRIMARY KEY, booth_id TEXT NOT NULL REFERENCES booths(id),
  status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')), created_at TEXT NOT NULL, used_at TEXT NULL);
CREATE TABLE donors_stats(id INTEGER PRIMARY KEY AUTOINCREMENT, booth_id TEXT NOT NULL REFERENCES booths(id),
  faculty TEXT NOT NULL, study_year INTEGER NOT NULL, registered_date TEXT NOT NULL);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def test_migration_from_iteration_2(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.executescript(ITER2_SCHEMA)
    raw.execute("INSERT INTO booths VALUES('c13','C-13','$argon2id$stary','0123012301','2026-10-26T00:00:00Z',2,7,'2026-10-26T00:00:00Z')")
    raw.execute("INSERT INTO game_sessions VALUES('s1','2026-10-26T00:00:00Z',1)")
    raw.execute("INSERT INTO game_attempts VALUES('s1','2026-10-26',4)")
    raw.execute("INSERT INTO donors_stats(booth_id,faculty,study_year,registered_date) VALUES('c13','W10',3,'2026-10-26')")
    dictionary = {"_note": "n", "faculties": [{"code": "W2", "name": "Wydział B"}, {"code": "W10", "name": "Wydział A"}]}
    raw.execute("INSERT INTO settings VALUES('dictionary', ?)", (json.dumps(dictionary),))
    raw.commit()
    raw.close()
    for _ in range(2):  # idempotentnie
        db.init_db()
        conn = db.connect()
        cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        assert {"bonus_attempts", "pass_booth", "pass_until"} <= cols("game_sessions")
        assert "best" in cols("game_attempts") and "pin_hash" in cols("booths")
        assert conn.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0] == 0
        s = conn.execute("SELECT * FROM game_sessions").fetchone()
        assert (s["has_won"], s["bonus_attempts"], s["pass_booth"]) == (1, 0, None)
        a = conn.execute("SELECT * FROM game_attempts").fetchone()
        assert (a["attempts"], a["best"]) == (4, 0)
        b = conn.execute("SELECT * FROM booths").fetchone()
        assert (b["matches_count"], b["rolls_count"], b["current_genotype"]) == (2, 7, "0123012301")
        assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 1
        facs = db.get_dictionary(conn)["faculties"]
        assert [f["code"] for f in facs] == ["W2", "W10", "INNE"]  # kolejność zachowana, Inne na końcu (raz)
        conn.close()


# --- dawca faktyczny (legitymacja) ----------------------------------------------
def actual_code(c, booth, number="AB 12-34", day="2020-05-17", **kw):
    return c.post("/api/volunteer/generate-code",
                  json={"booth_id": booth, "kind": "actual", "card_number": number, "card_date": day, **kw})


def test_actual_code_requires_card_data(admin, booth):
    for body in ({"kind": "actual"}, {"kind": "actual", "card_number": "A1"}, {"kind": "actual", "card_date": "2020-01-01"},
                 {"kind": "actual", "card_number": " - ", "card_date": "2020-01-01"},
                 {"kind": "actual", "card_number": "A" * 41, "card_date": "2020-01-01"},
                 {"kind": "actual", "card_number": "A1", "card_date": "nie-data"},
                 {"kind": "inny"}):
        r = admin.post("/api/volunteer/generate-code", json={"booth_id": booth, **body})
        assert r.status_code == 422, body
    r = actual_code(admin, booth)
    assert r.status_code == 200 and r.json()["kind"] == "actual"
    assert make_code(admin, booth_id=booth)  # domyślnie potencjalny


def test_actual_card_blocks_duplicates(admin, booth, other_clients):
    assert actual_code(admin, booth).status_code == 200
    r = actual_code(admin, booth, number=" ab1234 ")  # inna pisownia, ta sama legitymacja
    assert r.status_code == 409 and r.json()["detail"] == "Dla tej legitymacji jest już aktywny kod."
    assert actual_code(admin, booth, day="2020-05-18").status_code == 200  # inna data = inna legitymacja
    code = actual_code(admin, booth, number="zz9").json()["code"]
    p = other_clients()
    assert p.get(f"/api/donor/check-code?kod={code}").json()["kind"] == "actual"
    assert register(p, code).status_code == 200
    r = actual_code(admin, booth, number="ZZ-9")
    assert r.status_code == 409 and r.json()["detail"] == "Ta legitymacja jest już zarejestrowana w systemie."


def test_actual_card_reusable_after_expiry_or_cancel(admin, booth, monkeypatch):
    code = actual_code(admin, booth).json()["code"]
    assert admin.post(f"/api/admin/codes/{code}/cancel", json={}).status_code == 200
    code2 = actual_code(admin, booth).json()["code"]
    set_clock(monkeypatch, config.now() + timedelta(minutes=config.code_ttl_minutes() + 1))
    assert actual_code(admin, booth).status_code == 200
    assert code2


def test_actual_bonus_is_20_and_sums(admin, booth, other_clients):
    p = other_clients()
    new_session(p)
    d = register(p, actual_code(admin, booth).json()["code"]).json()
    assert d["kind"] == "actual" and d["bonus_attempts_granted"] == 20 and d["attempts_left"] == 25
    d = register(p, make_code(admin, booth_id=booth)).json()
    assert d["bonus_attempts_granted"] == 10 and d["attempts_left"] == 35


def test_register_actual_race_second_card_is_409(admin, booth, other_clients, conn):
    """Dwa kody z tą samą legitymacją (np. wygenerowane przed rejestracją) nie dają dwóch rejestracji."""
    c1 = actual_code(admin, booth).json()["code"]
    conn.execute("UPDATE registration_codes SET status='EXPIRED' WHERE code=?", (c1,))
    c2 = actual_code(admin, booth).json()["code"]
    conn.execute("UPDATE registration_codes SET status='ACTIVE' WHERE code=?", (c1,))
    assert register(other_clients(), c1).status_code == 200
    r = register(other_clients(), c2)
    assert r.status_code == 409
    assert conn.execute("SELECT status FROM registration_codes WHERE code=?", (c2,)).fetchone()[0] == "ACTIVE"
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 1


def test_stats_potential_actual(admin, booth, client):
    register(client, make_code(admin, booth_id=booth), "W4N", 1)
    register(client, make_code(admin, booth_id=booth), "W4N", 2)
    register(client, actual_code(admin, booth).json()["code"], "W4N", 3)
    register(client, actual_code(admin, booth, number="X2").json()["code"], "W3", 3)
    s = client.get("/api/stats/live").json()
    top = s["faculties"][0]
    assert (top["code"], top["potential"], top["actual"], top["total"]) == ("W4N", 2, 1, 3)
    w3 = next(f for f in s["faculties"] if f["code"] == "W3")
    assert (w3["potential"], w3["actual"], w3["total"]) == (0, 1, 1)
    assert s["total"] == 4 and s["total_actual"] == 2 and s["total_potential"] == 2
    me = volunteer_me(admin, booth)
    assert me["registered_count"] == 4 and me["registered_potential"] == 2 and me["registered_actual"] == 2
    sm = admin.get("/api/admin/summary?date=all").json()
    assert sm["registered"] == 4 and sm["podium"][0]["total"] == 3


def volunteer_me(c, booth):
    return c.get(f"/api/volunteer/me?booth_id={booth}").json()


def test_card_number_never_stored_in_plain(admin, booth, client, conn):
    number, day = "LEG-998877", "2019-03-04"
    code = actual_code(admin, booth, number=number, day=day).json()["code"]
    register(client, code)
    dump = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        dump.append(str([tuple(r) for r in conn.execute(f"SELECT * FROM {t}")]))
    blob = "\n".join(dump)
    assert "998877" not in blob and "LEG998877" not in blob and day not in blob
    h = conn.execute("SELECT card_hash FROM actual_donor_cards").fetchone()[0]
    from app import cards
    assert h == cards.card_hash("leg 998-877", day) and len(h) == 64
    assert conn.execute("SELECT kind FROM donors_stats").fetchone()[0] == "actual"


def test_fake_registrations_include_actual(admin, booth):
    admin.post("/api/admin/test/fake-registrations", json={"count": 500})
    s = admin.get("/api/stats/live").json()
    assert s["total"] == 500 and 0 < s["total_actual"] < 500


# --- terminy stanowisk (/graj bez stoiska) ---------------------------------------
def test_public_booth_list(admin, booth, other_clients, monkeypatch):
    monkeypatch.setattr(config, "today", lambda: "2026-11-04")
    admin.post("/api/admin/booths", json={"id": "w4", "name": "Budynek W-4", "building": "W-4",
                                          "date_from": "2026-11-02", "date_to": "2026-11-06"})
    admin.post("/api/admin/booths", json={"id": "old", "name": "Stare", "building": "A-1",
                                          "date_from": "2026-10-01", "date_to": "2026-11-03"})
    assert admin.patch("/api/admin/booths/c13", json={"building": "C-13", "date_from": "2026-11-05",
                                                      "date_to": "2026-11-09"}).status_code == 200
    assert admin.put("/api/admin/booth-hours", json={"hours": " 10:00-16:00 "}).json() == {"hours": "10:00-16:00"}
    anon = other_clients()
    d = anon.get("/api/booths/public").json()
    assert d["hours"] == "10:00-16:00"
    assert d["booths"] == [{"building": "W-4", "name": "Budynek W-4", "date_from": "2026-11-02", "date_to": "2026-11-06"},
                           {"building": "C-13", "name": "Budynek C-13", "date_from": "2026-11-05", "date_to": "2026-11-09"}]
    text = str(d)
    assert "genotype" not in text and "play_path" not in text and "t=" not in text
    assert admin.get("/api/admin/booth-hours").json() == {"hours": "10:00-16:00"}
    assert anon.put("/api/admin/booth-hours", json={"hours": "x"}).status_code == 401
    # walidacja dat
    assert admin.patch("/api/admin/booths/c13", json={"date_to": "2026-11-01"}).status_code == 422
    assert admin.patch("/api/admin/booths/c13", json={"date_from": "zle"}).status_code == 422
    assert admin.patch("/api/admin/booths/c13", json={"date_from": "", "date_to": ""}).status_code == 200
    assert anon.get("/api/booths/public").json()["booths"][-1] == {"building": "C-13", "name": "Budynek C-13",
                                                                   "date_from": None, "date_to": None}


def test_migration_adds_iteration3b_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.executescript(ITER2_SCHEMA)
    raw.execute("INSERT INTO booths VALUES('c13','C-13','x','0123012301','2026-10-26T00:00:00Z',0,0,'2026-10-26T00:00:00Z')")
    raw.execute("INSERT INTO registration_codes VALUES('C13-AAAA','c13','USED','2026-10-26T00:00:00Z','2026-10-26T00:01:00Z')")
    raw.execute("INSERT INTO donors_stats(booth_id,faculty,study_year,registered_date) VALUES('c13','W1',1,'2026-10-26')")
    raw.commit()
    raw.close()
    for _ in range(2):
        db.init_db()
        conn = db.connect()
        cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        assert {"building", "date_from", "date_to"} <= cols("booths")
        assert {"kind", "card_hash"} <= cols("registration_codes") and "kind" in cols("donors_stats")
        assert conn.execute("SELECT kind, card_hash FROM registration_codes").fetchone()[:] == ("potential", None)
        assert conn.execute("SELECT kind FROM donors_stats").fetchone()[0] == "potential"
        assert conn.execute("SELECT building, date_from FROM booths").fetchone()[:] == ("", None)
        assert conn.execute("SELECT COUNT(*) FROM actual_donor_cards").fetchone()[0] == 0
        conn.close()
