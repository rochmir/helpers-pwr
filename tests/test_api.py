import json
import re
import secrets
from datetime import timedelta

import pytest

from app import config, db

JSON = {"Content-Type": "application/json"}
CODE_RE = re.compile(r"^C13-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")


def new_session(c, booth=None):
    """Sesja gry; z ``booth`` od razu z przepustką (jak po zeskanowaniu QR)."""
    r = c.post("/api/game/session", json={})
    assert r.status_code == 200
    if booth:
        enter(c, booth)
    return r.json()


DEVICE = "ab" * 32


def enter(c, booth, t=None, device=DEVICE, consent=True, device_ext=None):
    from app import qrtoken
    body = {"booth_id": booth, "t": t or qrtoken.current(booth), "device": device, "consent": consent}
    if device_ext is not None:
        body["device_ext"] = device_ext
    return c.post("/api/game/enter", json=body)


def volunteer(other_clients, booth="c13", login="tester", password="tajne-haslo1"):
    v = other_clients()
    r = v.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    r = v.post("/api/auth/booth", json={"booth_id": booth})
    assert r.status_code == 200, r.text
    return v


def make_code(v, **body):
    r = v.post("/api/volunteer/generate-code", json=body)
    assert r.status_code == 200, r.text
    return r.json()["code"]


def register(c, code, faculty="W4N", device=None, **extra):
    """Wpisanie tokenu rejestracyjnego; domyślnie z nowym, losowym urządzeniem (jeden głos z urządzenia)."""
    return c.post("/api/donor/register", json={"code": code, "faculty": faculty,
                                               "device": device or secrets.token_hex(32), **extra})


# --- gra ------------------------------------------------------------------------
def test_session_and_roll(client, booth, other_clients):
    s = new_session(client, booth)
    assert s["attempts_left"] == 5 and s["has_won"] is False and s["token"] and s["bonus_attempts"] == 0
    r = client.post("/api/game/roll", json={"booth_id": booth})
    assert r.status_code == 200
    d = r.json()
    assert 5 <= d["matches"] <= 9 and d["win"] is False and d["attempts_left"] == 4
    assert len(d["player_genotype"]) == 10 and len(d["booth_genotype"]) == 10
    me = client.get("/api/game/me").json()
    assert me["attempts_left"] == 4 and me["has_won"] is False and me["best_today"] == d["matches"] == d["best_today"]
    st = other_clients().get(f"/api/booth/{booth}/state").json()  # anonimowo
    assert st["rolls_count"] == 1 and st["play_path"] is None


def test_session_reused_without_captcha(client):
    a = new_session(client)
    assert new_session(client)["token"] == a["token"]


def test_roll_requires_session_and_booth(client, booth):
    assert client.post("/api/game/roll", json={"booth_id": booth}).status_code == 401
    new_session(client, booth)
    assert client.post("/api/game/roll", json={"booth_id": "nope"}).status_code == 404


def test_roll_limit_then_daily_reset(client, booth, monkeypatch):
    new_session(client, booth)
    for i in range(5):
        assert client.post("/api/game/roll", json={"booth_id": booth}).status_code == 200
    r = client.post("/api/game/roll", json={"booth_id": booth})
    assert r.status_code == 429 and r.json()["attempts_left"] == 0 and r.json()["detail"] == "Limit prób na tym stanowisku na dziś wykorzystany. Zagraj na innym stanowisku albo wróć jutro."
    assert client.get(f"/api/booth/{booth}/state").json()["rolls_count"] == 5
    monkeypatch.setattr(config, "today", lambda: "2099-01-01")
    assert client.get("/api/game/me").json()["attempts_left"] == 5
    # sól dobowa się zmieniła, więc klucz urządzenia znikł: trzeba ponownie zeskanować kod ze stoiska
    assert client.post("/api/game/roll", json={"booth_id": booth}).status_code == 403
    assert enter(client, booth).status_code == 200
    assert client.post("/api/game/roll", json={"booth_id": booth}).status_code == 200


def test_forced_win(client, booth, monkeypatch):
    from app import game
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    new_session(client, booth)
    old = client.get(f"/api/booth/{booth}/state").json()["genotype"]
    d = client.post("/api/game/roll", json={"booth_id": booth}).json()
    assert d["win"] is True and d["matches"] == 10 and d["has_won"] is True
    assert d["player_genotype"] == old == d["booth_genotype"]
    st = client.get(f"/api/booth/{booth}/state").json()
    assert st["matches_count"] == 1 and st["genotype"] != old
    # druga wygrana w tej sesji niemożliwa
    d2 = client.post("/api/game/roll", json={"booth_id": booth}).json()
    assert d2["win"] is False and d2["matches"] <= 9
    assert client.get(f"/api/booth/{booth}/state").json()["matches_count"] == 1
    # inna sesja może wygrać; genotyp w historii jest oznaczony
    conn = db.connect()
    assert conn.execute("SELECT matched_at FROM genotype_history WHERE genotype=?", (old,)).fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM genotype_history WHERE booth_id=?", (booth,)).fetchone()[0] == 2
    conn.close()


def test_header_token_fallback(client, booth):
    token = new_session(client, booth)["token"]
    client.cookies.clear()
    assert client.get("/api/game/me").status_code == 401
    r = client.get("/api/game/me", headers={"X-Game-Token": token})
    assert r.status_code == 200
    assert "hp_game" in r.headers.get("set-cookie", "")
    client.cookies.clear()
    assert client.post("/api/game/roll", json={"booth_id": booth}, headers={"X-Game-Token": token}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/game/me", headers={"X-Game-Token": token + "x"}).status_code == 401


# --- wolontariusz ---------------------------------------------------------------
def test_volunteer_auth(booth, other_clients):
    v = other_clients()
    ok = {"login": "tester", "password": "tajne-haslo1"}
    assert v.post("/api/auth/login", json={**ok, "password": "zle-haslo-1"}).status_code == 401
    assert v.post("/api/auth/login", json={**ok, "login": "nikt"}).status_code == 401
    assert v.get("/api/auth/me").status_code == 401
    assert v.get("/api/volunteer/me").status_code == 401
    r = v.post("/api/auth/login", json={**ok, "login": " Tester "})  # login bez rozróżniania wielkości liter
    assert r.status_code == 200 and r.json() == {"login": "tester", "role": "volunteer", "booth": None}
    assert v.get("/api/auth/me").json() == {"login": "tester", "role": "volunteer", "booth": None}
    # bez stoiska akcje na stoisku dają 409
    assert v.get("/api/volunteer/me").status_code == 409
    assert v.post("/api/volunteer/generate-code", json={}).status_code == 409
    assert v.post("/api/auth/booth", json={"booth_id": "zzz"}).status_code == 404
    r = v.post("/api/auth/booth", json={"booth_id": "c13"})
    assert r.status_code == 200 and r.json()["booth"] == {"id": "c13", "name": "Budynek C-13"}
    assert v.get("/api/auth/me").json()["booth"] == {"id": "c13", "name": "Budynek C-13"}
    me = v.get("/api/volunteer/me").json()
    assert me["role"] == "volunteer" and me["booth"]["id"] == "c13" and me["codes"] == []
    v.post("/api/auth/logout", json={})
    assert v.get("/api/auth/me").status_code == 401


def test_volunteer_throttle(booth, other_clients):
    v = other_clients()
    bad = {"login": "tester", "password": "zle-haslo-1"}
    for _ in range(10):
        assert v.post("/api/auth/login", json=bad).status_code == 401
    # po 10 błędach nawet dobre hasło jest blokowane (per login)
    assert v.post("/api/auth/login", json={**bad, "password": "tajne-haslo1"}).status_code == 429


def test_volunteer_permissions(admin, booth, other_clients):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    v = volunteer(other_clients)
    assert v.post("/api/volunteer/generate-code", json={"booth_id": "w4"}).status_code == 403
    code = make_code(v)
    assert CODE_RE.match(code)
    for path in ("/api/admin/booths", "/api/admin/wins", "/api/admin/settings", "/api/admin/students", "/api/admin/codes", "/api/admin/dictionary",
                 "/api/admin/summary", "/api/admin/days", "/api/admin/export-csv", "/api/admin/volunteers"):
        assert v.get(path).status_code == 403, path
    assert v.put("/api/admin/dictionary", json={"faculties": []}).status_code == 403
    # kod z innego stoiska
    other_code = make_code(admin, booth_id="w4")
    assert other_code.startswith("W4-")
    assert v.post(f"/api/volunteer/codes/{other_code}/cancel", json={}).status_code == 403
    assert v.post(f"/api/volunteer/codes/{code}/cancel", json={}).json() == {"ok": True}
    assert v.post(f"/api/volunteer/codes/{code}/cancel", json={}).status_code == 409
    # bez logowania
    assert other_clients().get("/api/volunteer/me").status_code == 401


def test_admin_login(client):
    assert client.post("/api/auth/login", json={"login": "admin", "password": "zly"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"login": "admin", "password": "test-admin-secret"})
    assert r.json() == {"login": "admin", "role": "admin", "booth": None}
    assert client.get("/api/auth/me").json() == {"login": "admin", "role": "admin", "booth": None}
    assert client.get("/api/admin/booths").status_code == 200
    client.post("/api/auth/logout", json={})
    assert client.get("/api/auth/me").status_code == 401
    # stare punkty logowania nie istnieją
    assert client.post("/api/admin/login", json={"secret": "test-admin-secret"}).status_code == 404
    assert client.post("/api/volunteer/auth", json={}).status_code == 404


def test_code_generation_format(admin, booth):
    codes = {make_code(admin, booth_id=booth) for _ in range(30)}
    assert len(codes) == 30 and all(CODE_RE.match(c) for c in codes)
    r = admin.post("/api/volunteer/generate-code", json={})
    assert r.status_code == 400
    r = admin.post("/api/volunteer/generate-code", json={"booth_id": booth}).json()
    assert r["confirm_path"] == f"/potwierdz?kod={r['code']}" and r["expires_at"].endswith("Z")


# --- rejestracja ----------------------------------------------------------------
def test_register_flow(admin, booth, other_clients, client):
    code = make_code(admin, booth_id=booth)
    chk = client.get(f"/api/donor/check-code?kod= {code.lower()} ").json()
    assert chk == {"valid": True, "booth_name": "Budynek C-13", "kind": "potential", "bonus": config.CUP_VOTE_BONUS}
    r = register(client, code)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["faculty_name"] == "Wydział Informatyki i Telekomunikacji" and d["booth_name"] == "Budynek C-13"
    assert client.get(f"/api/donor/check-code?kod={code}").json() == {"valid": False}
    assert register(client, code).status_code == 410
    assert register(client, "C13-ZZZZ").status_code == 404
    conn = db.connect()
    assert conn.execute("SELECT status FROM registration_codes WHERE code=?", (code,)).fetchone()[0] == "USED"
    conn.close()


def test_register_expired(admin, booth, client, monkeypatch):
    code = make_code(admin, booth_id=booth)
    later = config.now() + timedelta(minutes=config.code_ttl_minutes() + 1)
    monkeypatch.setattr(config, "now", lambda: later)
    assert client.get(f"/api/donor/check-code?kod={code}").json() == {"valid": False}
    assert register(client, code).status_code == 410
    conn = db.connect()
    assert conn.execute("SELECT status FROM registration_codes WHERE code=?", (code,)).fetchone()[0] == "EXPIRED"
    conn.close()


def test_register_invalid_dictionary(admin, booth, client):
    code = make_code(admin, booth_id=booth)
    assert register(client, code, faculty="XX").status_code == 422
    assert client.post("/api/donor/register", json={"code": code, "faculty": "W4N"}).status_code == 422  # brak urządzenia
    assert client.post("/api/donor/register", json={"code": code, "faculty": "W4N", "device": "zly"}).status_code == 422
    assert register(client, code, faculty="W13").status_code == 200  # token nie został zużyty


def test_donors_stats_privacy(admin, booth, client):
    """§3.4 regulaminu Pucharu: wydział, znacznik czasu i skrót urządzenia; bez roku, stoiska, typu, tokenu i legitymacji."""
    code = make_code(admin, booth_id=booth)
    register(client, code, device="cd" * 32)
    conn = db.connect()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(donors_stats)")]
    assert cols == ["id", "faculty", "created_at", "device_hash"]
    assert "card_hash" not in [r[1] for r in conn.execute("PRAGMA table_info(registration_codes)")]
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='actual_donor_cards'").fetchone() is None
    row = conn.execute("SELECT * FROM donors_stats").fetchone()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["created_at"])
    assert re.fullmatch(r"[0-9a-f]{32}", row["device_hash"]) and row["device_hash"] != "cd" * 16
    assert code not in json.dumps([tuple(r) for r in conn.execute("SELECT * FROM donors_stats")])
    conn.close()


# --- statystyki i admin ---------------------------------------------------------
def seed_regs(admin, client, booth):
    for fac in ("W4N", "W4N", "W4N", "W13", "W3"):
        assert register(client, make_code(admin, booth_id=booth), fac).status_code == 200


def test_live_stats(admin, booth, client):
    seed_regs(admin, client, booth)
    new_session(client, booth)
    client.post("/api/game/roll", json={"booth_id": booth})
    s = client.get("/api/stats/live").json()
    assert s["total"] == 5
    assert len(s["faculties"]) == 15
    # kolejność słownika (to nie jest ranking), same punkty
    assert [f["code"] for f in s["faculties"]][:4] == ["W1", "W2", "W3", "W4N"]
    assert {f["code"]: f["count"] for f in s["faculties"] if f["count"]} == {"W4N": 3, "W13": 1, "W3": 1}
    assert all(set(f) == {"code", "name", "count", "actual", "potential"} for f in s["faculties"])
    assert s["total_potential"] == 5 and s["total_actual"] == 0
    assert s["booths"] == [{"id": "c13", "name": "Budynek C-13", "registered": 5, "actual": 0, "matches_count": 0, "rolls_count": 1}]
    assert s["game"] == {"rolls": 1, "matches": 0, "players": 1}


def test_admin_summary_day_vs_all(admin, booth, client, monkeypatch):
    conn = db.connect()
    seed_regs(admin, client, booth)
    conn.execute("UPDATE donors_stats SET created_at='2020-01-01T12:00:00Z' WHERE id<=2")
    today = config.today()
    d = admin.get(f"/api/admin/summary?date={today}").json()
    assert d["scope"] == "day" and d["date"] == today and d["registered"] == 3 and d["registered_total"] == 5
    # remis: kolejność ze słownika (W3, W4N, W13), nie alfabetyczna
    assert [(f["code"], f["count"]) for f in d["podium"]] == [("W3", 1), ("W4N", 1), ("W13", 1)]
    assert "battle" not in d and "cup" in d
    a = admin.get("/api/admin/summary?date=all").json()
    assert a["scope"] == "all" and a["registered"] == 5 and a["podium"][0]["code"] == "W4N"
    assert a["podium"][0]["count"] == 3 and len(a["podium"]) == 3
    old = admin.get("/api/admin/summary?date=2020-01-01").json()
    assert old["registered"] == 2 and old["game"] == {"players": 0, "rolls": 0, "matches": 0}
    assert admin.get("/api/admin/summary?date=zle").status_code == 422
    days = admin.get("/api/admin/days").json()
    assert today in days and "2020-01-01" in days and days == sorted(days, reverse=True)
    conn.close()


def test_admin_summary_game_by_day(admin, booth, client, monkeypatch):
    from app import game
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    new_session(client, booth)
    client.post("/api/game/roll", json={"booth_id": booth})
    day = admin.get(f"/api/admin/summary?date={config.today()}").json()["game"]
    assert day == {"players": 1, "rolls": 1, "matches": 1}
    assert admin.get("/api/admin/summary?date=all").json()["game"] == {"players": 1, "rolls": 1, "matches": 1}
    assert admin.get("/api/admin/summary?date=2001-01-01").json()["game"]["matches"] == 0


def test_csv_export(admin, booth, client):
    seed_regs(admin, client, booth)
    r = admin.get("/api/admin/export-csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "id,faculty,created_at"
    assert len(lines) == 6 and lines[1].startswith("1,W4N,20")
    assert "device_hash" not in r.text
    r = admin.get("/api/admin/export-csv?set=tokeny")
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "booth_id,kind,date,count" and lines[1] == f"c13,potential,{config.today()},5"


def test_dictionary_put(admin, booth, client):
    d = admin.get("/api/admin/dictionary").json()
    assert "_note" in d and len(d["faculties"]) == 15 and d["faculties"][-1] == {"code": "INNE", "name": "Inne"}
    assert all(set(f) == {"code", "name"} for f in d["faculties"])
    pub = client.get("/api/dictionary/faculties").json()
    assert set(pub) == {"faculties"}
    facs = d["faculties"]
    bad = [
        [],
        [{"code": "A", "name": ""}],
        [{"code": "A", "name": "a"}, {"code": "A", "name": "b"}],
        [{"code": "A B", "name": "a"}],
    ]
    for b in bad:
        assert admin.put("/api/admin/dictionary", json={"faculties": b}).status_code == 422, b
    assert admin.put("/api/admin/dictionary", json={"nope": 1}).status_code == 422
    # usunięcie wydziału z rejestracjami -> 409, bez rejestracji -> OK
    register(client, make_code(admin, booth_id=booth), "W4N")
    without_w4 = [f for f in facs if f["code"] != "W4N"]
    r = admin.put("/api/admin/dictionary", json={"faculties": without_w4})
    assert r.status_code == 409 and "W4N" in r.json()["detail"]
    without_w1 = [f for f in facs if f["code"] != "W1"]
    assert admin.put("/api/admin/dictionary", json={"faculties": without_w1}).status_code == 200
    assert len(client.get("/api/dictionary/faculties").json()["faculties"]) == 14
    assert admin.get("/api/admin/dictionary").json()["_note"]


def test_booth_admin_crud(admin, booth):
    assert admin.post("/api/admin/booths", json={"id": "c13", "name": "x"}).status_code == 409
    assert admin.post("/api/admin/booths", json={"id": "C 1", "name": "x"}).status_code == 422
    assert admin.post("/api/admin/booths", json={"id": "z1", "name": " "}).status_code == 422
    row = admin.get("/api/admin/booths").json()[0]
    assert row["id"] == "c13" and set(row) == {"id", "name", "current_genotype", "genotype_updated_at",
                                               "matches_count", "rolls_count", "registered", "active_codes",
                                               "building", "date_from", "date_to", "is_lecture"}
    g = admin.post("/api/admin/booths/c13/reset-genotype", json={}).json()["genotype"]
    assert g != row["current_genotype"] and len(g) == 10
    code = make_code(admin, booth_id="c13")
    assert admin.get("/api/admin/booths").json()[0]["active_codes"] == 1
    assert len(admin.get("/api/admin/codes?booth_id=c13&status=active").json()) == 1
    assert admin.delete("/api/admin/booths/c13", headers=JSON).status_code == 409
    assert admin.post(f"/api/admin/codes/{code}/cancel", json={}).status_code == 200
    admin.post("/api/admin/booths", json={"id": "tmp", "name": "T"})
    assert admin.delete("/api/admin/booths/tmp", headers=JSON).status_code == 200
    assert admin.delete("/api/admin/booths/tmp", headers=JSON).status_code == 404


# --- ogólne ---------------------------------------------------------------------
def test_json_content_type_required(client, booth):
    r = client.post("/api/game/session", content="{}", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    r = client.post("/api/game/session", data={"a": "b"})
    assert r.status_code == 415
    assert client.get("/api/config").status_code == 200


def test_headers(client):
    r = client.get("/api/config")
    assert r.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert r.headers["pragma"] == "no-cache"
    assert "challenges.cloudflare.com" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "same-origin"
    d = r.json()
    assert d["turnstile_site_key"] is None and d["public_url"] == "https://helpers-pwr.rupary.pl"
    assert d["facebook_url"] == "https://www.facebook.com/samorzadpwr"  # domyślny profil Samorządu z seedu
    assert d["legal_updated_at"].endswith("Z") and d["cup_deadline"] == "2026-12-11T15:30:00Z"
    assert d["contest_deadline"] == "2026-12-11T15:00:00Z"
    h = client.get("/healthz")
    assert h.json() == {"ok": True} and "content-security-policy" in h.headers and h.headers["cache-control"] == "no-cache"


def test_versioned_static_dev_no_cache(client, monkeypatch):
    from app.main import VERSIONED_PREFIX
    monkeypatch.setenv("DEV_NO_CACHE", "1")
    css = client.get(VERSIONED_PREFIX + "style.css")
    assert css.status_code == 200 and css.headers["cache-control"] == "no-cache"


def test_versioned_static(client):
    from app.main import VERSIONED_PREFIX
    page = client.get("/")
    assert page.headers["cache-control"] == "no-cache"
    assert f'href="{VERSIONED_PREFIX}style.css"' in page.text and 'href="/static/style.css"' not in page.text
    css = client.get(VERSIONED_PREFIX + "style.css")
    assert css.status_code == 200 and "immutable" in css.headers["cache-control"]


def test_qr(client):
    r = client.get("/api/qr.svg", params={"path": "/graj?stoisko=c13"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/svg+xml" and b"<svg" in r.content
    assert client.get("/api/qr.svg", params={"path": "graj"}).status_code == 400
    assert client.get("/api/qr.svg", params={"path": "//evil.com"}).status_code == 400
    assert client.get("/api/qr.svg", params={"path": "/" + "a" * 200}).status_code == 400


def test_pages(client):
    from app.main import STATIC_DIR
    if not (STATIC_DIR / "stoisko.html").exists():
        pytest.skip("brak app/static")
    assert client.get("/stoisko/c13").status_code == 200
    assert client.get("/stoisko/Bad!").status_code == 404
    for url in ("/", "/graj", "/puchar", "/potwierdz", "/statystyki", "/login", "/dokumenty", "/dokumenty/regulamin-konkursu"):
        assert client.get(url).status_code == 200, url
    r = client.get("/bitwa", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/puchar"


def test_bootstrap_booths(client, monkeypatch):
    # stary format id:nazwa:pin (pin ignorowany), nowy id:nazwa, wpis bez nazwy pomijany
    monkeypatch.setenv("BOOTSTRAP_BOOTHS", "c13:Budynek C-13:123456, w4:Budynek W-4:654321,c14:Budynek C-14,zle")
    db.bootstrap_booths()
    db.bootstrap_booths()
    c = db.connect()
    assert [r["id"] for r in c.execute("SELECT id FROM booths ORDER BY id")] == ["c13", "c14", "w4", "zajecia"]
    assert c.execute("SELECT name FROM booths WHERE id='c14'").fetchone()[0] == "Budynek C-14"
    assert c.execute("SELECT name FROM booths WHERE id='c13'").fetchone()[0] == "Budynek C-13"
    c.close()


def test_check_code_global_miss_limit(client, monkeypatch):
    from app.routes import donor
    monkeypatch.setattr(donor, "CHECK_MISSES_PER_MINUTE", 3)
    for _ in range(3):
        assert client.get("/api/donor/check-code?kod=C13-XXXX").json() == {"valid": False}
    assert client.get("/api/donor/check-code?kod=C13-XXXX").status_code == 429


def test_admin_volunteer_me_without_booth(admin, booth):
    r = admin.get("/api/volunteer/me")
    assert r.status_code == 200 and r.json()["booth"] is None and r.json()["role"] == "admin"
    r = admin.get("/api/volunteer/me?booth_id=c13")
    assert r.json()["booth"]["id"] == "c13"
