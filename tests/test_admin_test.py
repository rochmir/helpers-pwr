import json
import sqlite3

import pytest

from app import config, db, testing

from test_api import new_session, make_code, register

OLD_DONORS = ("CREATE TABLE donors_stats(id INTEGER PRIMARY KEY AUTOINCREMENT, booth_id TEXT NOT NULL, "
              "faculty TEXT NOT NULL, major TEXT NOT NULL, study_year INTEGER NOT NULL, registered_date TEXT NOT NULL)")


# --- migracja (usunięcie kierunków) ---------------------------------------------
def test_migration_drops_major(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.execute(OLD_DONORS)
    raw.execute("INSERT INTO donors_stats(booth_id,faculty,major,study_year,registered_date) VALUES('c13','W4N','Informatyka',2,'2026-10-01')")
    raw.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old = {"_note": "n", "faculties": [{"code": "W4N", "name": "Informatyki", "majors": ["Informatyka", "Inny kierunek"]}]}
    raw.execute("INSERT INTO settings VALUES('dictionary', ?)", (json.dumps(old),))
    raw.commit()
    raw.close()
    for _ in range(2):  # idempotentnie
        db.init_db()
        conn = db.connect()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(donors_stats)")]
        assert "major" not in cols and {"faculty", "study_year", "registered_date"} <= set(cols)
        row = conn.execute("SELECT * FROM donors_stats").fetchone()
        assert (row["faculty"], row["study_year"], row["registered_date"]) == ("W4N", 2, "2026-10-01")
        assert db.get_dictionary(conn) == {"_note": "n", "faculties": [{"code": "W4N", "name": "Informatyki"}, {"code": "INNE", "name": "Inne"}]}
        conn.close()


def test_migration_adds_donor_booth_id(tmp_path, monkeypatch):
    """Baza produkcyjna sprzed stoiska przy wpisie statystyki: /api/stats/live padał na d.booth_id."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    raw = sqlite3.connect(config.db_path())
    raw.execute("CREATE TABLE donors_stats(id INTEGER PRIMARY KEY AUTOINCREMENT, faculty TEXT NOT NULL, "
                "study_year INTEGER NOT NULL, registered_date TEXT NOT NULL)")
    raw.execute("INSERT INTO donors_stats(faculty,study_year,registered_date) VALUES('W4N',2,'2026-10-01')")
    raw.commit()
    raw.close()
    from app.routes import stats
    for _ in range(2):  # idempotentnie
        db.init_db()
        conn = db.connect()
        assert "booth_id" in [r[1] for r in conn.execute("PRAGMA table_info(donors_stats)")]
        db.create_booth(conn, f"b{_}", "Stoisko")
        conn.commit()
        out = stats.live(conn)
        assert out["total"] == 1 and all(b["registered"] == 0 for b in out["booths"])
        conn.close()


# --- autoryzacja ----------------------------------------------------------------
def test_volunteer_and_anonymous_forbidden(client, booth, other_clients):
    from test_api import volunteer
    v = volunteer(other_clients)
    calls = [("post", "force-win", {"booth_id": booth}), ("post", "arm-win", {}), ("post", "reset-my-game", {}),
             ("post", "fake-registrations", {"count": 1}), ("post", "wipe", {"confirm": "USUŃ"}), ("get", "status", None)]
    for who, codes in ((v, (403,)), (other_clients(), (401, 403))):
        for method, path, body in calls:
            r = getattr(who, method)(f"/api/admin/test/{path}", **({"json": body} if body is not None else {}))
            assert r.status_code in codes, (path, r.status_code)
    assert client.get(f"/api/booth/{booth}/state").json()["matches_count"] == 0


# --- force-win ------------------------------------------------------------------
def test_force_win(admin, booth):
    before = admin.get(f"/api/booth/{booth}/state").json()
    r = admin.post("/api/admin/test/force-win", json={"booth_id": booth})
    assert r.status_code == 200
    d = r.json()
    assert d["old_genotype"] == before["genotype"] and d["new_genotype"] != d["old_genotype"]
    st = admin.get(f"/api/booth/{booth}/state").json()
    assert st["genotype"] == d["new_genotype"] and st["matches_count"] == 1 and st["rolls_count"] == 0
    conn = db.connect()
    assert conn.execute("SELECT matched_at FROM genotype_history WHERE genotype=?", (d["old_genotype"],)).fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM genotype_history").fetchone()[0] == 2
    conn.close()
    assert admin.post("/api/admin/test/force-win", json={"booth_id": "nope"}).status_code == 404


# --- arm-win / reset-my-game / status -------------------------------------------
def test_arm_win_requires_session(admin):
    r = admin.post("/api/admin/test/arm-win", json={})
    assert r.status_code == 400 and "/graj" in r.json()["detail"]
    assert admin.post("/api/admin/test/reset-my-game", json={}).status_code == 400
    assert admin.get("/api/admin/test/status").json() == {"armed": False, "game_session": False, "attempts_left": None}


def test_arm_win_wins_even_after_has_won(admin, booth, monkeypatch):
    from app import game
    new_session(admin, booth)
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    conn = db.connect()
    conn.execute("UPDATE game_sessions SET has_won=1")
    conn.close()
    assert admin.get("/api/admin/test/status").json() == {"armed": False, "game_session": True, "attempts_left": 5}
    assert admin.post("/api/admin/test/arm-win", json={}).json() == {"ok": True}
    assert admin.get("/api/admin/test/status").json()["armed"] is True
    old = admin.get(f"/api/booth/{booth}/state").json()["genotype"]
    d = admin.post("/api/game/roll", json={"booth_id": booth}).json()
    assert d["win"] is True and d["matches"] == 10 and d["player_genotype"] == old and d["has_won"] is True
    st = admin.get(f"/api/booth/{booth}/state").json()
    assert st["matches_count"] == 1 and st["genotype"] != old
    # uzbrojenie zużyte
    assert admin.get("/api/admin/test/status").json()["armed"] is False
    assert admin.post("/api/game/roll", json={"booth_id": booth}).json()["win"] is False


def test_arm_not_consumed_when_limit_reached(admin, booth, monkeypatch):
    from app import game
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    new_session(admin, booth)
    for _ in range(5):
        admin.post("/api/game/roll", json={"booth_id": booth})
    admin.post("/api/admin/test/arm-win", json={})
    assert admin.post("/api/game/roll", json={"booth_id": booth}).status_code == 429
    assert admin.get("/api/admin/test/status").json()["armed"] is True


def test_reset_my_game(admin, booth, monkeypatch):
    from app import game
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    new_session(admin, booth)
    assert admin.post("/api/game/roll", json={"booth_id": booth}).json()["has_won"] is True
    me = admin.get("/api/game/me").json()
    assert me["attempts_left"] == 4 and me["has_won"] is True and me["best_today"] == 10
    assert admin.post("/api/admin/test/reset-my-game", json={}).json() == {"ok": True, "attempts_left": 5}
    me = admin.get("/api/game/me").json()
    assert me["attempts_left"] == 5 and me["has_won"] is False and me["best_today"] == 0


# --- fake-registrations ---------------------------------------------------------
def test_fake_registrations(admin, booth):
    r = admin.post("/api/admin/test/fake-registrations", json={"count": 30})
    assert r.status_code == 200 and r.json() == {"created": 30}
    r = admin.post("/api/admin/test/fake-registrations", json={"count": 5, "booth_id": booth, "date": "2020-01-01"})
    assert r.json() == {"created": 5}
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 35
    rows = conn.execute("SELECT * FROM donors_stats WHERE registered_date='2020-01-01'").fetchall()
    assert len(rows) == 5 and all(x["booth_id"] == booth and 1 <= x["study_year"] <= 7 for x in rows)
    codes = {f["code"] for f in db.get_dictionary(conn)["faculties"]}
    assert all(x["faculty"] in codes for x in conn.execute("SELECT faculty FROM donors_stats"))
    conn.close()
    assert admin.post("/api/admin/test/fake-registrations", json={"count": 0}).status_code == 422
    assert admin.post("/api/admin/test/fake-registrations", json={"count": 501}).status_code == 422
    assert admin.post("/api/admin/test/fake-registrations", json={"count": 1, "date": "zle"}).status_code == 422
    assert admin.post("/api/admin/test/fake-registrations", json={"count": 1, "booth_id": "nope"}).status_code == 404


def test_fake_registrations_without_booths_409(admin):
    assert admin.post("/api/admin/test/fake-registrations", json={"count": 3}).status_code == 409


# --- wipe -----------------------------------------------------------------------
def test_wipe(admin, booth, client, monkeypatch):
    from app import game
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    new_session(admin, booth)
    admin.post("/api/game/roll", json={"booth_id": booth})
    assert register(client, make_code(admin, booth_id=booth)).status_code == 200
    admin.post("/api/admin/test/arm-win", json={})
    before = admin.get(f"/api/booth/{booth}/state").json()
    dict_before = admin.get("/api/admin/dictionary").json()
    for bad in ({"confirm": "usuń"}, {"confirm": ""}, {"confirm": "TAK"}):
        assert admin.post("/api/admin/test/wipe", json=bad).status_code == 400
    assert admin.get("/api/stats/live").json()["total"] == 1
    assert admin.post("/api/admin/test/wipe", json={"confirm": "USUŃ"}).json() == {"ok": True}
    st = admin.get(f"/api/booth/{booth}/state").json()
    assert st["matches_count"] == 0 and st["rolls_count"] == 0 and st["genotype"] != before["genotype"]
    conn = db.connect()
    for t in ("donors_stats", "registration_codes", "game_sessions", "game_attempts"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
    assert [tuple(r) for r in conn.execute("SELECT genotype, booth_id, matched_at FROM genotype_history")] == [(st["genotype"], booth, None)]
    assert conn.execute("SELECT COUNT(*) FROM booths").fetchone()[0] == 1
    conn.close()
    assert admin.get("/api/admin/dictionary").json() == dict_before
    assert not testing.is_armed("x")
    # konto wolontariusza nadal działa
    assert admin.post("/api/volunteer/auth", json={"login": "tester", "password": "tajne-haslo1", "booth_id": booth}).status_code == 200
