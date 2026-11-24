"""Stanowisko „Zajęcia”: poza publicznymi wykazami, ekran bez logowania pod statycznym linkiem, blok „Więcej o akcji”,
a także aktualizacja seedu dokumentów prawnych i nowe ustępy regulaminów."""
import hashlib

from app import config, db, legal
from test_api import JSON, enter, new_session, vote_new
from test_iter4 import roll


def screen_token(admin, booth_id="zajecia"):
    """Token ekranu stoiska z panelu admina (GET; ``None``, gdy ekran wyłączony)."""
    url = admin.get(f"/api/admin/booths/{booth_id}/screen").json()["url"]
    return url.rsplit("/", 1)[1] if url else None


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
    assert client.get(f"/api/screen/{screen_token(admin)}/state").json()["play_path"] is not None


# --- ekran bez logowania ----------------------------------------------------------
def test_screen_with_good_token_works_without_login(admin, other_clients):
    token = screen_token(admin)
    assert admin.get("/api/admin/booths/zajecia/screen").json()["url"] == f"{config.public_url()}/ekran/{token}"
    guest = other_clients()
    page = guest.get(f"/ekran/{token}")
    assert page.status_code == 200 and "booth-name" in page.text
    assert page.headers["cache-control"] == "no-store" and page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["x-robots-tag"] == "noindex"
    st = guest.get(f"/api/screen/{token}/state").json()
    assert st["play_path"].startswith("/graj?stoisko=zajecia&t=") and 0 < st["qr_seconds_left"] <= 60
    assert "screen_token" not in st and token not in str(st)
    assert guest.get("/api/booth/zajecia/state").json()["play_path"] is None  # bez tokenu nic


def test_screen_with_bad_token_is_404_and_hides_play_path(admin, booth, other_clients):
    token = screen_token(admin)
    guest = other_clients()
    for bad in ("zly", token[:-1] + ("A" if token[-1] != "A" else "B"), token + "x", "żółw", "x" * 65):
        assert guest.get(f"/ekran/{bad}").status_code == 404, bad
        assert guest.get(f"/api/screen/{bad}/state").status_code == 404, bad
        assert guest.get(f"/zajecia/{bad}", follow_redirects=False).status_code == 404, bad


def test_token_of_one_booth_does_not_open_another(admin, booth, other_clients):
    admin.post("/api/admin/booths", json={"id": "w4", "name": "W-4"})
    t_c13 = admin.post("/api/admin/booths/c13/screen", json={}).json()["url"].rsplit("/", 1)[1]
    t_w4 = admin.post("/api/admin/booths/w4/screen", json={}).json()["url"].rsplit("/", 1)[1]
    assert t_c13 != t_w4
    guest = other_clients()
    assert guest.get(f"/api/screen/{t_c13}/state").json()["play_path"].startswith("/graj?stoisko=c13&")
    assert guest.get(f"/api/screen/{t_w4}/state").json()["play_path"].startswith("/graj?stoisko=w4&")


def test_empty_or_missing_token_never_matches(client, booth):
    conn = db.connect()
    assert db.booth_by_screen_token(conn, "") is None and db.booth_by_screen_token(conn, None) is None
    assert db.booth_by_screen_token(conn, "x" * 64) is None  # c13 nie ma tokenu (NULL)
    conn.close()
    assert client.get("/api/admin/booths/c13/screen").json() == {"url": None}


def test_regular_booth_still_requires_staff(admin, booth, other_clients):
    guest = other_clients()
    assert guest.get(f"/api/booth/{booth}/state").json()["play_path"] is None
    assert admin.get(f"/api/booth/{booth}/state").json()["play_path"]


def test_booth_screen_rotation_invalidates_old_link(admin, booth, other_clients):
    old = admin.post(f"/api/admin/booths/{booth}/screen", json={}).json()["url"].rsplit("/", 1)[1]
    r = admin.post("/api/admin/booths/zajecia/screen", json={})  # osobny ekran nie rusza c13
    assert r.status_code == 200
    r = admin.post(f"/api/admin/booths/{booth}/screen", json={})
    assert r.status_code == 200 and r.json()["url"].rsplit("/", 1)[1] != old
    new = r.json()["url"].rsplit("/", 1)[1]
    guest = other_clients()
    assert guest.get(f"/ekran/{old}").status_code == 404
    assert guest.get(f"/api/screen/{old}/state").status_code == 404
    assert guest.get(f"/ekran/{new}").status_code == 200
    assert screen_token(admin, booth) == new
    assert [b for b in admin.get("/api/admin/booths").json() if b["id"] == booth][0]["has_screen"] is True


def test_lecture_code_opens_screen_without_login(admin, other_clients, booth):
    code = screen_token(admin)
    assert code.isalpha() and code.islower() and len(code) == 6  # łatwy kod: sześć liter
    guest = other_clients()
    page = guest.get(f"/zajecia/{code}", follow_redirects=False)
    assert page.status_code == 200 and "booth-name" in page.text
    assert page.headers["cache-control"] == "no-store" and page.headers["x-robots-tag"] == "noindex"
    assert guest.get(f"/api/screen/{code}/state").json()["play_path"].startswith("/graj?stoisko=zajecia&t=")
    token = admin.post(f"/api/admin/booths/{booth}/screen", json={}).json()["url"].rsplit("/", 1)[1]
    assert guest.get(f"/zajecia/{token}").status_code == 404  # kod innego stanowiska nie otwiera Zajęć


def test_lecture_code_is_memorable_on_rotation(admin):
    old = screen_token(admin)
    new = admin.post("/api/admin/booths/zajecia/screen", json={}).json()["url"].rsplit("/", 1)[1]
    assert new != old and new.isalpha() and new.islower() and len(new) == 6


def test_public_screen_outside_booth_dates_has_no_play_path(admin, booth, other_clients):
    token = admin.post(f"/api/admin/booths/{booth}/screen", json={}).json()["url"].rsplit("/", 1)[1]
    guest = other_clients()
    admin.patch(f"/api/admin/booths/{booth}", json={"date_from": "2020-01-01", "date_to": "2020-01-02"})
    st = guest.get(f"/api/screen/{token}/state").json()
    assert st["play_path"] is None and st["closed"] is True
    assert admin.get(f"/api/booth/{booth}/state").json()["play_path"]  # personel dalej ma link
    admin.patch(f"/api/admin/booths/{booth}", json={"date_from": "2020-01-01", "date_to": "2099-12-31"})
    st = guest.get(f"/api/screen/{token}/state").json()
    assert st["play_path"].startswith(f"/graj?stoisko={booth}&") and st["closed"] is False


def test_ensure_lecture_booth_copies_old_settings_token(client):
    conn = db.connect()
    conn.execute("UPDATE booths SET screen_token=NULL WHERE id='zajecia'")
    db.set_setting(conn, "lecture_screen_token", "STARY_TOKEN_1234")
    db.ensure_lecture_booth(conn)
    assert conn.execute("SELECT screen_token FROM booths WHERE id='zajecia'").fetchone()[0] == "STARY_TOKEN_1234"
    db.ensure_lecture_booth(conn)  # drugi start nic nie zmienia
    assert conn.execute("SELECT screen_token FROM booths WHERE id='zajecia'").fetchone()[0] == "STARY_TOKEN_1234"
    conn.close()
    assert client.get("/ekran/STARY_TOKEN_1234").status_code == 200


def test_reserved_booth_ids_are_refused(admin):
    for bid in ("ekran", "login", "zajecia"):
        assert admin.post("/api/admin/booths", json={"id": bid, "name": "x"}).status_code == 422, bid


def test_booth_screen_admin_only(booth, other_clients):
    anon = other_clients()
    assert anon.get("/api/admin/booths/zajecia/screen").status_code == 401
    assert anon.post("/api/admin/booths/zajecia/screen", json={}).status_code == 401
    v = other_clients()
    v.post("/api/auth/login", json={"login": "tester", "password": "tajne-haslo1"})
    assert v.get("/api/admin/booths/zajecia/screen").status_code == 403
    assert v.post("/api/admin/booths/zajecia/screen", json={}).status_code == 403


# --- brak wolontariusza -----------------------------------------------------------
def test_cup_qr_and_delete_are_409_for_lecture_booth(admin, booth):
    for category in ("nowy", "zarejestrowany", "faktyczny", "post"):
        r = admin.post("/api/volunteer/cup-qr", json={"category": category, "booth_id": "zajecia"})
        assert r.status_code == 409, category
    assert admin.delete("/api/admin/booths/zajecia", headers=JSON).status_code == 409
    assert any(b["id"] == "zajecia" for b in admin.get("/api/admin/booths").json())
    assert admin.post("/api/volunteer/cup-qr", json={"category": "nowy", "booth_id": booth}).status_code == 200  # zwykłe stoisko działa


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
    assert "ma podstawowy limit 5 prób na dobę na każdym stanowisku osobno." in k
    assert "Limit, o którym mowa w ust. 3, nie obejmuje prób dodatkowych (ust. 4)." in k
    p = client.get("/dokumenty/regulamin-pucharu").text
    assert "przyznaje uczestnikowi +10 dodatkowych prób w symulatorze edukacyjnym HLA Match Maker" in p
    assert "kod jest ważny do momentu zeskanowania" in p and "rok studiów" in p
    pol = client.get("/dokumenty/polityka-prywatnosci").text
    assert "hp_game" in pol and "fingerprint" in pol.lower() and "wyłącznie informację o wygenerowaniu jednorazowego kodu QR" in pol


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
