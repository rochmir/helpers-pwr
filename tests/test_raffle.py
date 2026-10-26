import pytest

from app import db, game

from test_api import new_session


def _roll(c, booth):
    return c.post("/api/game/roll", json={"booth_id": booth})


def _hist(g):
    conn = db.connect()
    try:
        return dict(conn.execute("SELECT * FROM genotype_history WHERE genotype=?", (g,)).fetchone())
    finally:
        conn.close()


def _real_win(c, booth, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    new_session(c, booth)
    return _roll(c, booth).json()


def test_win_stores_genotype_and_time(admin, booth, monkeypatch):
    d = _real_win(admin, booth, monkeypatch)
    assert d["win"] is True
    h = _hist(d["player_genotype"])
    assert d["won_at"] == h["matched_at"] and h["is_test"] == 0
    conn = db.connect()
    s = conn.execute("SELECT won_genotype, won_at FROM game_sessions").fetchone()
    conn.close()
    assert (s["won_genotype"], s["won_at"]) == (d["player_genotype"], h["matched_at"])
    me = admin.get("/api/game/me").json()
    assert me["won_genotype"] == d["player_genotype"] and me["won_at"] == h["matched_at"]


def test_no_win_has_no_won_fields(admin, booth, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    new_session(admin, booth)
    d = _roll(admin, booth).json()
    assert d["won_at"] is None
    me = admin.get("/api/game/me").json()
    assert me["won_genotype"] is None and me["won_at"] is None


def test_test_wins_are_flagged_and_excluded(admin, booth, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: False)
    old = admin.post("/api/admin/test/force-win", json={"booth_id": booth}).json()["old_genotype"]
    assert _hist(old)["is_test"] == 1
    new_session(admin, booth)
    armed = admin.get(f"/api/booth/{booth}/state").json()["genotype"]
    admin.post("/api/admin/test/arm-win", json={})
    assert _roll(admin, booth).json()["win"] is True
    assert _hist(armed)["is_test"] == 1
    r = admin.get("/api/admin/raffle").json()
    assert r["entries_count"] == 0 and r["entries"] == [] and r["draws"] == []
    assert admin.post("/api/admin/raffle/draw", json={}).status_code == 409


def test_draw_only_eligible_never_repeats(admin, booth, other_clients, monkeypatch):
    monkeypatch.setattr(game, "is_win", lambda rng=None: True)
    won = []
    for _ in range(3):
        c = other_clients()
        new_session(c, booth)
        won.append(_roll(c, booth).json()["player_genotype"])
    admin.post("/api/admin/test/force-win", json={"booth_id": booth})  # testowe, poza losowaniem
    ov = admin.get("/api/admin/raffle").json()
    assert ov["entries_count"] == 3 and {e["genotype"] for e in ov["entries"]} == set(won)
    assert ov["entries"][0]["booth_name"] == "Budynek C-13"
    drawn = []
    for i in range(3):
        r = admin.post("/api/admin/raffle/draw", json={})
        assert r.status_code == 200
        d = r.json()
        assert d["genotype"] in won and d["genotype"] not in drawn and d["remaining"] == 2 - i
        assert d["matched_at"] == _hist(d["genotype"])["matched_at"]
        drawn.append(d["genotype"])
    assert sorted(drawn) == sorted(won)
    r = admin.post("/api/admin/raffle/draw", json={})
    assert r.status_code == 409 and "Brak" in r.json()["detail"]
    assert [x["genotype"] for x in admin.get("/api/admin/raffle").json()["draws"]] == drawn


def test_raffle_requires_admin(client, booth, other_clients):
    from test_api import volunteer
    for who, codes in ((volunteer(other_clients), (403,)), (other_clients(), (401, 403))):
        assert who.get("/api/admin/raffle").status_code in codes
        assert who.post("/api/admin/raffle/draw", json={}).status_code in codes


def test_wipe_clears_raffle(admin, booth, monkeypatch):
    _real_win(admin, booth, monkeypatch)
    assert admin.post("/api/admin/raffle/draw", json={}).status_code == 200
    assert admin.post("/api/admin/test/wipe", json={"confirm": "USUŃ"}).status_code == 200
    r = admin.get("/api/admin/raffle").json()
    assert r["entries_count"] == 0 and r["draws"] == []
