from datetime import timedelta

from app import config, db
from test_api import CODE_RE, JSON, make_code, new_session, register, volunteer


def promo(v, **body):
    return make_code(v, kind="promo", **body)


def redeem(c, code):
    return c.post("/api/donor/redeem-promo", json={"code": code})


def test_volunteer_promo_only_own_booth(admin, booth, other_clients):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "Budynek W-4"})
    v = volunteer(other_clients)
    r = v.post("/api/volunteer/generate-code", json={"kind": "promo", "booth_id": "w4"})
    assert r.status_code == 403
    r = v.post("/api/volunteer/generate-code", json={"kind": "promo"})
    assert r.status_code == 200 and CODE_RE.match(r.json()["code"]) and r.json()["kind"] == "promo"
    assert r.json()["confirm_path"] == "/potwierdz?kod=" + r.json()["code"]
    conn = db.connect()
    assert conn.execute("SELECT booth_id FROM promo_codes").fetchone()[0] == "c13"
    assert conn.execute("SELECT COUNT(*) FROM registration_codes").fetchone()[0] == 0
    conn.close()
    assert v.post("/api/volunteer/generate-code", json={"kind": "bogus"}).status_code == 422


def test_redeem_gives_five_and_sums(admin, booth, other_clients):
    v = volunteer(other_clients)
    p = other_clients()
    new_session(p)
    d = redeem(p, promo(v)).json()
    assert d["bonus_attempts_granted"] == config.PROMO_BONUS == 5 and d["attempts_left"] == 10 and d["token"]
    assert d["booth_name"] == "Budynek C-13" and d["play_path"].startswith("/graj?stoisko=c13&t=")
    assert redeem(p, promo(v)).json()["attempts_left"] == 15
    # po rejestracji tez sie sumuje (+10)
    assert register(p, make_code(v)).json()["attempts_left"] == 25
    assert p.get("/api/game/me").json()["bonus_attempts"] == 20


def test_redeem_without_session_creates_one(admin, booth, other_clients):
    v, p = volunteer(other_clients), other_clients()
    d = redeem(p, promo(v)).json()
    assert d["bonus_attempts_granted"] == 5 and d["token"]
    me = p.get("/api/game/me").json()
    assert me["bonus_attempts"] == 5


def test_redeem_twice_410_expired_410_unknown_404(admin, booth, other_clients):
    v, p = volunteer(other_clients), other_clients()
    code = promo(v)
    assert redeem(p, code).status_code == 200
    r = redeem(p, code)
    assert r.status_code == 410 and "użyty lub wygasł" in r.json()["detail"]
    assert p.get("/api/game/me").json()["bonus_attempts"] == 5  # drugi raz bez bonusu
    old = promo(v)
    conn = db.connect()
    conn.execute("UPDATE promo_codes SET created_at=? WHERE code=?",
                 (config.iso(config.now() - timedelta(minutes=config.code_ttl_minutes() + 1)), old))
    conn.close()
    assert redeem(p, old).status_code == 410
    assert redeem(p, "C13-ZZZZ").status_code == 404


def test_redeem_does_not_touch_stats(admin, booth, other_clients):
    v, p = volunteer(other_clients), other_clients()
    stats_before = admin.get("/api/stats/live").json()
    battle_before = admin.get("/api/stats/battle").json()
    vme_before = v.get("/api/volunteer/me").json()
    assert redeem(p, promo(v)).status_code == 200
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM donors_stats").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM actual_donor_cards").fetchone()[0] == 0
    conn.close()
    assert admin.get("/api/stats/live").json()["total"] == stats_before["total"] == 0
    assert admin.get("/api/stats/battle").json() == battle_before
    vme = v.get("/api/volunteer/me").json()
    for k in ("registered_count", "registered_potential", "registered_actual", "matches_count", "rolls_count"):
        assert vme[k] == vme_before[k]


def test_register_with_promo_code_404(admin, booth, other_clients):
    v, p = volunteer(other_clients), other_clients()
    code = promo(v)
    assert register(p, code).status_code == 404
    assert p.post("/api/donor/redeem-promo", json={"code": make_code(v)}).status_code == 404  # i odwrotnie
    assert redeem(p, code).status_code == 200  # nieudana rejestracja nie zuzyla kodu


def test_check_code_promo_kind(admin, booth, other_clients):
    v, p = volunteer(other_clients), other_clients()
    code = promo(v)
    assert p.get("/api/donor/check-code", params={"kod": code.lower()}).json() == {
        "valid": True, "booth_name": "Budynek C-13", "kind": "promo"}
    redeem(p, code)
    assert p.get("/api/donor/check-code", params={"kod": code}).json() == {"valid": False}


def test_codes_unique_across_tables(admin, booth, other_clients, monkeypatch):
    v = volunteer(other_clients)
    reg = make_code(v)
    assert reg
    monkeypatch.setattr(db.secrets, "choice", lambda a: "X")
    conn = db.connect()
    conn.execute("INSERT INTO promo_codes(code,booth_id,status,created_at) VALUES('C13-XXXX','c13','ACTIVE',?)", (config.now_iso(),))
    assert db.unique_code(conn, "c13") is None  # kazda proba koliduje z kodem promo
    conn.close()
    assert v.post("/api/volunteer/generate-code", json={"kind": "potential"}).status_code == 503


def test_code_lists_show_kind_and_cancel(admin, booth, other_clients):
    v = volunteer(other_clients)
    pc, rc = promo(v), make_code(v)
    codes = {c["code"]: c for c in v.get("/api/volunteer/me").json()["codes"]}
    assert codes[pc]["kind"] == "promo" and codes[rc]["kind"] == "potential" and codes[pc]["expires_at"]
    adm = {c["code"]: c for c in admin.get("/api/admin/codes").json()}
    assert adm[pc]["kind"] == "promo" and adm[pc]["booth_id"] == "c13" and adm[rc]["kind"] == "potential"
    assert [c["code"] for c in admin.get("/api/admin/codes", params={"status": "active"}).json()].count(pc) == 1
    assert admin.get("/api/admin/booths").json()[0]["active_codes"] == 2
    # anulowanie przez wolontariusza i admina
    assert v.post(f"/api/volunteer/codes/{pc}/cancel", json={}).json() == {"ok": True}
    assert v.post(f"/api/volunteer/codes/{pc}/cancel", json={}).status_code == 409
    assert redeem(other_clients(), pc).status_code == 410
    pc2 = promo(v)
    assert admin.post(f"/api/admin/codes/{pc2}/cancel", json={}).json() == {"ok": True}
    assert redeem(other_clients(), pc2).status_code == 410
    assert v.post("/api/volunteer/codes/NIE-MA/cancel", json={}).status_code == 404


def test_cancel_promo_other_booth_forbidden(admin, booth, other_clients):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "Budynek W-4"})
    code = promo(admin, booth_id="w4")
    v = volunteer(other_clients)
    assert v.post(f"/api/volunteer/codes/{code}/cancel", json={}).status_code == 403


def test_booth_with_promo_codes_cannot_be_deleted(admin, booth, other_clients):
    promo(volunteer(other_clients))
    assert admin.delete(f"/api/admin/booths/{booth}", headers=JSON).status_code == 409


def test_wipe_clears_promo_codes(admin, booth, other_clients):
    promo(volunteer(other_clients))
    assert admin.post("/api/admin/test/wipe", json={"confirm": "USUŃ"}).json() == {"ok": True}
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM promo_codes").fetchone()[0] == 0
    conn.close()


def test_promo_migration_idempotent(client):
    conn = db.connect()
    conn.executescript(db.SCHEMA)
    db._migrate(conn)
    conn.executescript(db.SCHEMA)
    assert conn.execute("SELECT COUNT(*) FROM promo_codes").fetchone()[0] == 0
    conn.close()
