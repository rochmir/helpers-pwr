"""Stanowisko „Zajęcia”: poza publicznymi wykazami, ekran bez logowania pod statycznym linkiem, blok „Więcej o akcji”,
a także aktualizacja seedu dokumentów prawnych i nowe ustępy regulaminów."""
import hashlib

from app import config, db, legal
from test_api import JSON, enter, new_session, vote_new
from test_iter4 import roll


def screen_token(admin):
    r = admin.get("/api/admin/lecture-screen")
    assert r.status_code == 200
    return r.json()["token"]


# --- wykazy -----------------------------------------------------------------------
def test_lecture_booth_exists_and_is_hidden_from_public_lists(admin, booth, client):
    rows = {b["id"]: b for b in admin.get("/api/admin/booths").json()}
    assert rows["zajecia"]["is_lecture"] is True and rows["zajecia"]["name"] == "Zajęcia" and rows[booth]["is_lecture"] is False
    assert [b["id"] for b in client.get("/api/booths").json()] == [booth]
    assert [b["name"] for b in client.get("/api/booths/public").json()["booths"]] == ["Budynek C-13"]
    assert [b["id"] for b in client.get("/api/stats/live").json()["booths"]] == [booth]


def test_lecture_booth_creation_is_idempotent(client):
    conn = db.connect()
    db.ensure_lecture_booth(conn)
    db.init_db()
    assert conn.execute("SELECT COUNT(*) FROM booths WHERE id='zajecia' AND is_lecture=1").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM genotype_history WHERE booth_id='zajecia'").fetchone()[0] == 1
    conn.close()


def test_lecture_hits_and_attempts_are_counted(admin, client):
    new_session(client, "zajecia")
    assert roll(client, "zajecia").status_code == 200
    assert admin.get("/api/booth/zajecia/state").json()["rolls_count"] == 1
    assert client.get("/api/stats/live").json()["game"]["rolls"] == 1


def test_lecture_booth_ignores_booth_dates(admin, client):
    assert admin.patch("/api/admin/booths/zajecia", json={"date_from": "2020-01-01", "date_to": "2020-01-02"}).status_code == 200
    new_session(client, "zajecia")
    assert roll(client, "zajecia").status_code == 200


# --- ekran bez logowania ----------------------------------------------------------
def test_screen_with_good_token_works_without_login(admin, other_clients):
    token = screen_token(admin)
    assert admin.get("/api/admin/lecture-screen").json()["url"] == f"{config.public_url()}/zajecia/{token}"
    guest = other_clients()
    page = guest.get(f"/zajecia/{token}")
    assert page.status_code == 200 and "booth-name" in page.text
    st = guest.get("/api/booth/zajecia/state", params={"screen": token}).json()
    assert st["play_path"].startswith("/graj?stoisko=zajecia&t=") and 0 < st["qr_seconds_left"] <= 60
    assert guest.get("/api/booth/zajecia/state").json()["play_path"] is None  # bez tokenu nic


def test_screen_with_bad_token_is_404_and_hides_play_path(admin, booth, other_clients):
    token = screen_token(admin)
    guest = other_clients()
    for bad in ("zly", token[:-1] + ("A" if token[-1] != "A" else "B"), token + "x", "żółw"):
        assert guest.get(f"/zajecia/{bad}").status_code == 404, bad
        assert guest.get("/api/booth/zajecia/state", params={"screen": bad}).json()["play_path"] is None
    # token Zajęć nie otwiera zwykłego stoiska
    assert guest.get(f"/api/booth/{booth}/state", params={"screen": token}).json()["play_path"] is None


def test_regular_booth_still_requires_staff(admin, booth, other_clients):
    guest = other_clients()
    assert guest.get(f"/api/booth/{booth}/state").json()["play_path"] is None
    assert admin.get(f"/api/booth/{booth}/state").json()["play_path"]


def test_rotation_invalidates_old_link(admin, other_clients):
    old = screen_token(admin)
    r = admin.post("/api/admin/lecture-screen/rotate", json={})
    assert r.status_code == 200 and r.json()["token"] != old
    guest = other_clients()
    assert guest.get(f"/zajecia/{old}").status_code == 404
    assert guest.get("/api/booth/zajecia/state", params={"screen": old}).json()["play_path"] is None
    assert guest.get(f"/zajecia/{r.json()['token']}").status_code == 200
    assert screen_token(admin) == r.json()["token"]


def test_lecture_screen_admin_only(booth, other_clients):
    anon = other_clients()
    assert anon.get("/api/admin/lecture-screen").status_code == 401
    assert anon.post("/api/admin/lecture-screen/rotate", json={}).status_code == 401
    v = other_clients()
    v.post("/api/auth/login", json={"login": "tester", "password": "tajne-haslo1"})
    assert v.get("/api/admin/lecture-screen").status_code == 403
    assert v.post("/api/admin/lecture-screen/rotate", json={}).status_code == 403


# --- brak wolontariusza -----------------------------------------------------------
def test_cup_qr_and_delete_are_409_for_lecture_booth(admin, booth):
    for category in ("nowy", "zarejestrowany", "faktyczny", "post"):
        r = admin.get(f"/api/volunteer/cup-qr?category={category}&booth_id=zajecia")
        assert r.status_code == 409, category
    assert admin.delete("/api/admin/booths/zajecia", headers=JSON).status_code == 409
    assert any(b["id"] == "zajecia" for b in admin.get("/api/admin/booths").json())
    assert admin.get(f"/api/volunteer/cup-qr?category=nowy&booth_id={booth}").status_code == 200  # zwykłe stoisko działa


# --- po zeskanowaniu --------------------------------------------------------------
def test_pass_is_lecture_flag(admin, booth, client):
    assert new_session(client)["pass_is_lecture"] is False
    assert enter(client, "zajecia").status_code == 200
    me = client.get("/api/game/me").json()
    assert me["pass_booth"] == "zajecia" and me["pass_is_lecture"] is True
    assert enter(client, booth).status_code == 200
    me = client.get("/api/game/me").json()
    assert me["pass_booth"] == booth and me["pass_is_lecture"] is False


def test_graj_page_has_lecture_block_and_limit_texts(client):
    html = client.get("/graj").text
    assert 'id="lecture-section"' in html and "Więcej o akcji" in html
    assert "na każdym stanowisku" in html and "łącznie na wszystkich stanowiskach" not in html


# --- aktualizacja seedu dokumentów ------------------------------------------------
def test_seed_update_replaces_untouched_v1_only_once(client, monkeypatch):
    conn = db.connect()
    slug = "regulamin-pucharu"
    title, new_body = legal.split_title((legal.LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
    old_body = "Stara treść seedu.\n"
    monkeypatch.setitem(legal.PREVIOUS_SEED_SHA256, slug, (hashlib.sha256(old_body.encode()).hexdigest(),))
    conn.execute("UPDATE legal_documents SET body_md=?, version=1, updated_at='2026-01-01T00:00:00Z' WHERE slug=?", (old_body, slug))
    legal.seed(conn)
    row = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
    assert row["body_md"] == new_body and row["version"] == 2 and row["updated_at"] > "2026-01-01T00:00:00Z"
    ver = conn.execute("SELECT * FROM legal_document_versions WHERE slug=?", (slug,)).fetchall()
    assert [(v["version"], v["body_md"], v["saved_by"]) for v in ver] == [(1, old_body, "system")]
    legal.seed(conn)  # drugi start nic nie zmienia
    again = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
    assert tuple(again) == tuple(row)
    assert conn.execute("SELECT COUNT(*) FROM legal_document_versions WHERE slug=?", (slug,)).fetchone()[0] == 1
    conn.close()


def test_seed_update_leaves_manually_edited_document(client, monkeypatch):
    conn = db.connect()
    slug = "regulamin-konkursu"
    monkeypatch.setitem(legal.PREVIOUS_SEED_SHA256, slug, (hashlib.sha256("Stara treść seedu.\n".encode()).hexdigest(),))
    conn.execute("UPDATE legal_documents SET body_md='Zmieniona w panelu.', version=3 WHERE slug=?", (slug,))
    before = tuple(conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone())
    legal.seed(conn)
    assert tuple(conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM legal_document_versions WHERE slug=?", (slug,)).fetchone()[0] == 0
    conn.close()


def test_previous_seed_hashes_are_not_the_current_text():
    for slug in legal.BASE_SLUGS:
        _, body = legal.split_title((legal.LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
        assert hashlib.sha256(body.encode()).hexdigest() not in legal.PREVIOUS_SEED_SHA256[slug]


# --- treść dokumentów -------------------------------------------------------------
def test_documents_contain_new_clauses(client):
    k = client.get("/dokumenty/regulamin-konkursu").text
    assert "na jedną sesję przeglądarki na każdym stanowisku, z zastrzeżeniem ust. 5." in k
    assert "Limit, o którym mowa w ust. 2, nie obejmuje prób dodatkowych." in k
    p = client.get("/dokumenty/regulamin-pucharu").text
    assert "Oddanie głosu uprawnia do dodatkowych prób w symulatorze HLA Match Maker" in p
    assert "ważny przez 60 sekund" in p and "rok studiów" in p
    pol = client.get("/dokumenty/polityka-prywatnosci").text
    assert "hp_game" in pol and "fingerprint" in pol.lower() and "Kodów QR nie zapisujemy" in pol


# --- /statystyki: kategorie dawców ------------------------------------------------
def test_live_stats_split_categories(admin, booth, client):
    vote_new(booth, "faktyczny", "W4N")
    vote_new(booth, "nowy", "W4N")
    s = client.get("/api/stats/live").json()
    w4 = next(f for f in s["faculties"] if f["code"] == "W4N")
    assert (w4["count"], w4["faktyczny"], w4["nowy"], w4["zarejestrowany"]) == (2, 1, 1, 0)
    assert s["booths"][0]["registered"] == 2 and s["booths"][0]["faktyczny"] == 1
    conn = db.connect()
    assert {r[1] for r in conn.execute("PRAGMA table_info(donors_stats)")} == {"id", "faculty", "created_at", "category", "study_year", "booth_id"}
    conn.close()
