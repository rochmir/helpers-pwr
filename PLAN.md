# helpersi-pwr — plan implementacji (źródło prawdy dla agentów)

Spec biznesowy: `/srv/infra/dkms_pwr/projekt.md`. Ten plik go **nadpisuje** tam, gdzie się różnią.
Docelowy adres: `https://helpers-pwr.rupary.pl` (tunel Cloudflare → `http://localhost:8010`).

## Twarde zasady (od właściciela)
1. **Zero danych osobowych na serwerze.** Imię/nazwisko/ksywka do certyfikatów żyją tylko w przeglądarce
   (canvas). Kolumny `matched_by_nickname` NIE MA. Nie zapisujemy IP (uvicorn `--no-access-log`, nie wysyłamy
   `remoteip` do Turnstile, nie logujemy IP nigdzie). Rejestracja dawcy nie przechowuje kodu ani pełnego
   znacznika czasu — tylko datę (`registered_date`), żeby nie dało się powiązać wpisu z osobą.
   **Wyjątek (losowanie finałowe):** zapisujemy anonimowo wzór trafienia 10/10 i jego godzinę (`genotype_history`,
   `game_sessions.won_genotype/won_at`, losowy `session_id`) — bez nicku, bez IP, bez niczego, co wskazuje osobę.
2. **Wygląd nieistotny teraz.** Właściciel dostarczy CSS i projekty certyfikatów później. Frontend: czysty,
   semantyczny HTML z sensownymi klasami/id, jeden `static/style.css` z minimalnym, neutralnym stylem.
   Renderery canvas = proste placeholdery, ale z kompletną logiką (dane, font preload, PNG, `<img>` fallback).
3. **Role:** admin (`ADMIN_SECRET`) ≠ wolontariusz (PIN stoiska). Wolontariusz widzi tylko swoje stoisko.
4. **eduroam:** zero blokad po IP. Ochrona przed botami = Cloudflare Turnstile.
5. Bez wymyślonych treści. Słownik kierunków to seed do weryfikacji, edytowalny w adminie.

## Stack (jak w opis-faktury)
Python 3.12, FastAPI, uvicorn (1 worker), stdlib `sqlite3` (WAL, `busy_timeout=5000`, `foreign_keys=ON`),
`itsdangerous` (podpisy), `argon2-cffi` (PIN-y), `segno` (QR SVG). Statyczny HTML/JS bez frameworka i bez
kroku budowania. Bez Jinja. Testy: pytest + httpx (`TestClient`).

## Układ katalogów
```
/home/roch/projekty/helpersi-pwr/
  Dockerfile  docker-compose.yml  .env.example  .dockerignore  .gitignore
  requirements.txt  requirements-dev.txt  README.md  PLAN.md
  app/
    main.py          # app, middleware (nagłówki), routing stron statycznych
    config.py        # env: ADMIN_SECRET, SECRET_KEY, DATA_DIR, PUBLIC_URL, TURNSTILE_*, CODE_TTL_MINUTES, COOKIE_SECURE, TZ
    db.py            # połączenie, schema, migracja, seed słownika
    auth.py          # podpisane cookies, zależności require_admin / require_volunteer / game_session
    captcha.py       # Turnstile siteverify (bez remoteip)
    game.py          # logika genotypów (czysta, testowalna)
    routes/          # game.py, volunteer.py, donor.py, stats.py, admin.py, misc.py
    seed_dictionary.json
    static/          # *.html, *.js, style.css, cert.js, common.js
  tests/
  data/              # wolumen (gitignored)
```

## Schemat SQLite (`$DATA_DIR/dkms.db`, DATA_DIR=/app/data)
```sql
booths(id TEXT PK CHECK(id GLOB '[a-z0-9]*'), name TEXT NOT NULL, pin_hash TEXT NOT NULL,
       current_genotype TEXT NOT NULL, genotype_updated_at TEXT NOT NULL,
       matches_count INTEGER NOT NULL DEFAULT 0, rolls_count INTEGER NOT NULL DEFAULT 0,
       created_at TEXT NOT NULL)
genotype_history(genotype TEXT PK, booth_id TEXT NOT NULL, created_at TEXT NOT NULL,
                 matched_at TEXT NULL,            -- brak nicku!
                 is_test INTEGER NOT NULL DEFAULT 0)  -- 1 = trafienie z narzędzi testowych (poza losowaniem)
game_sessions(session_id TEXT PK, created_at TEXT NOT NULL, has_won INTEGER NOT NULL DEFAULT 0,
              won_genotype TEXT NULL, won_at TEXT NULL)  -- wzór i godzina trafienia (= genotype_history.matched_at)
raffle_draws(id INTEGER PK AUTOINCREMENT, genotype TEXT NOT NULL REFERENCES genotype_history(genotype),
             drawn_at TEXT NOT NULL)
game_attempts(session_id TEXT, date TEXT, attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id,date))
registration_codes(code TEXT PK, booth_id TEXT NOT NULL REFERENCES booths(id),
                   status TEXT NOT NULL CHECK(status IN('ACTIVE','USED','EXPIRED')),
                   created_at TEXT NOT NULL, used_at TEXT NULL)
donors_stats(id INTEGER PK AUTOINCREMENT, booth_id TEXT NOT NULL REFERENCES booths(id),
             faculty TEXT NOT NULL, major TEXT NOT NULL, study_year INTEGER NOT NULL,
             registered_date TEXT NOT NULL)       -- YYYY-MM-DD, bez kodu i godziny
settings(key TEXT PK, value TEXT NOT NULL)        -- 'dictionary' = JSON słownika
```
Czasy: ISO 8601 UTC. „Dzień” (limit prób, podsumowania dzienne) = data w strefie `Europe/Warsaw` (`zoneinfo`).
Genotyp: 10 znaków z `0123`. Nowy genotyp musi być unikalny względem `genotype_history` (zapisywany tam przy
utworzeniu stoiska i każdej zmianie).

## Logika
**Losowanie** (`POST /api/game/roll`, body `{booth_id}`), jedna transakcja `BEGIN IMMEDIATE`:
- brak sesji → 401; stoisko nie istnieje → 404; `attempts` dziś ≥ 5 → 429 `{detail, attempts_left:0}`.
- `attempts += 1`, `booths.rolls_count += 1`.
- Wygrana z p = 1/300 (`game.WIN_ONE_IN`) **i tylko gdy sesja `has_won=0`**: odczyt
  `current_genotype` wewnątrz transakcji (więc wyścig nie istnieje), `matches_count += 1`, `has_won=1`,
  `genotype_history.matched_at` dla starego, nowy unikalny genotyp na stoisko. Zwraca stary genotyp jako trafiony.
  Tym samym znacznikiem czasu: `game_sessions.won_genotype/won_at` (do certyfikatu). Trafienie z `arm-win` /
  `force-win` dostaje `genotype_history.is_test=1`.
- Inaczej k ∈ {5:25, 6:35, 7:25, 8:10, 9:5}%; ciąg z dokładnie k zgodnymi pozycjami (losowe pozycje,
  na niezgodnych losowy *inny* symbol). Funkcje w `game.py` przyjmują `rng` do testów.
- Wolne od wyścigu: rolls/attempts liczone w tej samej transakcji.

**Kody rejestracyjne:** `{BOOTH_ID.upper()}-{4 znaki}` z alfabetu `23456789ABCDEFGHJKMNPQRSTUVWXYZ`
(bez 0/O/1/I/L). Unikalność po PK (retry). Ważność `CODE_TTL_MINUTES` (domyślnie 60) — wygaszane leniwie
(przy każdym odczycie/użyciu, `UPDATE ... SET status='EXPIRED' WHERE status='ACTIVE' AND created_at < ?`).
Wejście kodu normalizowane: upper, trim, usunięcie spacji, `O→0`? NIE — po prostu upper/trim.

**Rok studiów:** 1–5, 6 = Szkoła Doktorska, 7 = Pracownik PWr (etykiety w słowniku).

## Auth
- `SECRET_KEY` z env, inaczej losowy zapisany w `$DATA_DIR/secret_key` (chmod 600).
- **Sesja gry:** id = `secrets.token_urlsafe(24)`; token = podpis itsdangerous (`Signer`, salt `game`).
  Cookie `hp_game` (HttpOnly, SameSite=Lax, Secure gdy `COOKIE_SECURE=1`, max-age 30 dni) + ten sam token
  w JSON odpowiedzi → frontend trzyma w `localStorage['hp_game']` i wysyła nagłówek `X-Game-Token`, gdy
  cookie zniknie. Serwer akceptuje cookie lub nagłówek; jeśli tylko nagłówek — odnawia cookie.
- **Personel:** cookie `hp_staff` = `URLSafeTimedSerializer` (salt `staff`) z `{role:'admin'}` albo
  `{role:'volunteer', booth:'c13'}`; HttpOnly, SameSite=Strict, max-age 12h (admin) / 14h (wolontariusz).
  Admin to nadzbiór: `require_volunteer(booth)` przepuszcza też admina (admin może wygenerować kod dla
  dowolnego stoiska podając `booth_id`).
- `ADMIN_SECRET` porównywany `hmac.compare_digest`. PIN stoiska: min. 6 cyfr, argon2.
  Zmiana PIN-u stoiska unieważnia stare sesje wolontariuszy (w tokenie trzymaj 8 znaków hash-u `pin_hash`
  i porównuj).
- Throttle PIN w pamięci per stoisko (NIE per IP): po 10 błędach w 10 min stoisko blokuje logowanie na 5 min.
- CSRF: wszystkie POST/PUT/PATCH/DELETE pod `/api/` wymagają `Content-Type: application/json` (inaczej 415).
- **Turnstile** (`cf_turnstile` w body) wymagany przy: `POST /api/game/session`, `POST /api/donor/register`,
  `POST /api/volunteer/auth`, `POST /api/admin/login`. Wyłączony, gdy brak kluczy (lokalnie/testy) — warning w logu.
  `siteverify` bez `remoteip`. Opcjonalnie `TURNSTILE_EXEMPT=1` dla testów.

## Nagłówki
- `/api/*`: `Cache-Control: no-store, no-cache, must-revalidate`, `Pragma: no-cache`.
- Wszystko: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
  CSP: `default-src 'self'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`.
  **Żadnego inline JS** w HTML.

## Kontrakt API (JSON; błędy `{"detail": "komunikat po polsku"}`)
### Ogólne
- `GET /api/config` → `{turnstile_site_key: str|null, public_url: str}`
- `GET /api/qr.svg?path=/graj?stoisko=c13` → `image/svg+xml` QR z `PUBLIC_URL + path` (path musi zaczynać się od `/`, max 200 zn.)
- `GET /healthz` → `{ok:true}`
### Gra
- `GET /api/booth/{id}/state` → `{id, name, genotype, genotype_updated_at, matches_count, rolls_count, play_path:"/graj?stoisko=c13"}`
- `POST /api/game/session` `{cf_turnstile}` → `{token, attempts_left, has_won, won_genotype, won_at}` (+cookie). Jeśli ważna sesja już jest — zwraca ją (bez captchy).
- `GET /api/game/me` → `{attempts_left, has_won, won_genotype, won_at}` (ostatnie dwa `null` bez trafienia) lub 401
- `POST /api/game/roll` `{booth_id}` → `{matches:int(5..10), win:bool, player_genotype, booth_genotype, attempts_left, has_won, won_at}` (`won_at` = UTC ISO trafienia, `null` bez wygranej)
### Wolontariusz
- `POST /api/volunteer/auth` `{booth_id, pin, cf_turnstile}` → `{booth:{id,name}}` (+cookie)
- `POST /api/volunteer/logout` → `{ok}`
- `GET /api/volunteer/me` → `{role, booth:{id,name}, registered_count, matches_count, rolls_count, codes:[{code,status,created_at,expires_at}] (20 ostatnich)}`
- `POST /api/volunteer/generate-code` `{booth_id?}` (booth_id tylko dla admina) → `{code, expires_at, confirm_path:"/potwierdz?kod=C13-AB7K"}`
- `POST /api/volunteer/codes/{code}/cancel` → `{ok}` (tylko ACTIVE i własne stoisko)
### Dawca i statystyki
- `GET /api/dictionary/faculties` → `{faculties:[{code,name,majors:[str]}], study_years:[{value,label}]}`
- `GET /api/donor/check-code?kod=X` → `{valid:bool, booth_name?:str}` (do wstępnej walidacji z QR; nie zużywa kodu)
- `POST /api/donor/register` `{code, faculty, major, study_year, cf_turnstile}` → `{ok, faculty_name, booth_name}`;
  błędy: 404 nieznany kod, 410 użyty/wygasły, 422 wydział/kierunek/rok spoza słownika. Atomowo (`BEGIN IMMEDIATE`).
- `GET /api/stats/live` → `{total, faculties:[{code,name,count}] (wszystkie, malejąco), top_majors:[{faculty,major,count}] (5),
   booths:[{id,name,registered,matches_count,rolls_count}], game:{rolls,matches,players}}`
### Admin
- `POST /api/admin/login` `{secret, cf_turnstile}` / `POST /api/admin/logout` / `GET /api/admin/me` → `{role:'admin'}`
- `GET /api/admin/booths` → `[{id,name,current_genotype,genotype_updated_at,matches_count,rolls_count,registered,active_codes}]`
- `POST /api/admin/booths` `{id,name,pin}` (201) · `PATCH /api/admin/booths/{id}` `{name?,pin?}` ·
  `DELETE /api/admin/booths/{id}` (409, gdy ma rejestracje lub kody)
- `POST /api/admin/booths/{id}/reset-genotype` → `{genotype}`
- `GET /api/admin/codes?booth_id=&status=` (max 200, najnowsze) · `POST /api/admin/codes/{code}/cancel`
- `GET /api/admin/dictionary` / `PUT /api/admin/dictionary` (cały JSON w formacie jak `/api/dictionary/faculties`
  bez study_years; walidacja: unikalne kody, niepuste nazwy). Nie wolno usunąć wydziału, który ma rejestracje (409).
- `GET /api/admin/summary?date=YYYY-MM-DD|all` → `{scope:'day'|'all', date, registered:int, registered_total:int,
   podium:[{code,name,count}] (top3 w zakresie), top_major:{faculty,major,count}|null,
   game:{players, rolls, matches}}` (dla dnia: players = sesje z próbą tego dnia, rolls = suma prób dnia,
   matches = `genotype_history.matched_at` tego dnia w Europe/Warsaw)
- `GET /api/admin/days` → lista dat z jakąkolwiek aktywnością (do selecta)
- `GET /api/admin/export-csv` → `text/csv; charset=utf-8` z BOM, `id,booth_id,faculty,major,study_year,registered_date`

## Strony (FastAPI serwuje pliki z `app/static/`)
| URL | plik | rola |
|---|---|---|
| `/` | index.html | linki: Graj, Statystyki, Potwierdź rejestrację |
| `/stoisko/{id}` | stoisko.html | ekran pasywny: genotyp (▲●■★), liczniki, QR do `/graj?stoisko=id`, polling 2.5 s, animacja „Zebrano Genotyp 10/10!” przy zmianie |
| `/graj` | graj.html | gracz: Turnstile → sesja; „Losuj”; wynik porównania pozycja po pozycji; po 10/10 formularz ksywki → certyfikat 9:16 (tylko lokalnie) |
| `/wolontariusz` | wolontariusz.html | login (stoisko + PIN + Turnstile); wielki przycisk; duży kod + QR do `/potwierdz?kod=`; lista ostatnich kodów z „Anuluj”; liczniki stoiska; wyloguj |
| `/potwierdz` | potwierdz.html | kod (prefill z `?kod=`, check-code), kaskadowe selecty, opcjonalne imię i nazwisko (NIE wysyłane), Turnstile, po sukcesie certyfikat dawcy |
| `/statystyki` | statystyki.html | live ranking, odświeżanie co 10 s |
| `/admin` | admin.html | login; stoiska (CRUD, reset genotypu, PIN), kody, edytor słownika (textarea JSON), CSV, generator grafik (zakres dzień/całość, format 9:16 / 4:5 / 1:1) |

Wspólne JS: `common.js` (fetch wrapper z `X-Game-Token`, obsługa błędów, `loadTurnstile(container)` → Promise tokenu
w trybie explicit render, no-op gdy brak site key), `cert.js` (`ensureFonts()`, `renderPlayerCert(nick)`,
`renderDonorCert({name, facultyName})`, `renderSocial(summary, format)`, `showDownload(canvas, container, filename)`
— pokazuje `<img src=dataURL>`, link `download` i tekst „Kliknij przycisk Pobierz lub przytrzymaj palcem na obrazku,
aby zapisać go w galerii”). Font canvasu: `@font-face 'HelpersiCert'` z `/static/fonts/cert.woff2`; jeśli pliku
nie ma, `ensureFonts()` po `document.fonts.ready` spada na `system-ui, sans-serif` (diakrytyki działają w fontach
systemowych). Teksty UI po polsku.

## Docker
- `python:3.12-slim-bookworm`, user uid 10001, `WORKDIR /app`, `DATA_DIR=/app/data`, `VOLUME /app/data`,
  `EXPOSE 8000`, HEALTHCHECK `/healthz`, CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log`.
- compose: kontener `helpersi-pwr`, `ports: "127.0.0.1:8010:8000"` (cloudflared ma network_mode host),
  `./data:/app/data`, `env_file: .env`, `TZ=Europe/Warsaw`, logi json-file 10m×3, restart unless-stopped.

## Podział pracy
- **Sonnet A (backend + docker + testy):** wszystko poza `app/static/`.
- **Sonnet B (frontend):** `app/static/` wg kontraktu powyżej.
- **Opus:** integracja, przegląd, uruchomienie.

---
## Iteracja 2 (zmiany od właściciela)
1. **Bez kierunku studiów.** Usuwamy `major` wszędzie: słownik = tylko wydziały `{code,name}`, `donors_stats` bez kolumny
   `major` (migracja `ALTER TABLE donors_stats DROP COLUMN major`, jeśli istnieje; słownik w `settings` — usuń klucze
   `majors`), `POST /api/donor/register` `{code, faculty, study_year, cf_turnstile}` (nadmiarowe pola ignorowane),
   `stats/live` bez `top_majors`, `admin/summary` bez `top_major`, CSV bez `major`.
2. **Narzędzia testowe admina** (wszystkie `require_admin`, prefiks `/api/admin/test/`):
   - `POST force-win {booth_id}` → wykonuje prawdziwą logikę trafienia na stoisku (bez sesji gracza): `matches_count+1`,
     nowy unikalny genotyp, `matched_at` starego → `{old_genotype, new_genotype}`. Do testu animacji ekranu stoiska.
   - `POST arm-win` → następne losowanie **sesji gry z tej przeglądarki** (cookie `hp_game`/`X-Game-Token` admina) będzie
     10/10, także gdy `has_won=1`. Trzymane w pamięci (set session_id, 1 worker). Brak sesji gry → 400
     „Najpierw otwórz /graj w tej przeglądarce”. → `{ok:true}`
   - `POST reset-my-game` → dla sesji gry tej przeglądarki: usuń dzisiejsze próby, `has_won=0` → `{ok, attempts_left}`.
   - `POST fake-registrations {count:1..500, booth_id?:str, date?:YYYY-MM-DD}` → losowe wpisy `donors_stats`
     (losowy wydział ze słownika, rok 1..7, stoisko podane lub losowe istniejące, data podana lub dziś) → `{created}`.
     Brak stoisk → 409.
   - `POST wipe {confirm:"USUŃ"}` → kasuje donors_stats, registration_codes, game_sessions, game_attempts, zeruje
     raffle_draws, liczniki stoisk, nadaje każdemu stoisku nowy genotyp i odbudowuje genotype_history tylko z bieżących genotypów.
     Stoiska, PIN-y i słownik zostają. Zły confirm → 400. → `{ok}`
   - `GET status` → `{armed: bool, game_session: bool, attempts_left: int|null}` dla tej przeglądarki.
3. **Wygląd** (frontend): identyfikacja DKMS / Helpers' Generation, loga DKMS, Helpers' Generation, PWr jako lokalne
   pliki w `app/static/brand/`. Fonty self-hosted w `app/static/fonts/`. **Ikony z biblioteki (self-hosted), zero emoji
   i znaków-ikon** — kształty genotypu też jako ikony. Gra: animacja jednorękiego bandyty (10 bębnów zatrzymujących się
   kolejno na genotypie gracza). Admin: sekcja „Testy” + podgląd certyfikatów i grafik.

---
## Iteracja 3 (zmiany od właściciela; nadpisuje wcześniejsze punkty tam, gdzie się różnią)
Wszystkie zmiany schematu to idempotentne migracje w `db._migrate` (ALTER TABLE ADD COLUMN gdy brak kolumny,
CREATE TABLE IF NOT EXISTS); produkcyjna baza migruje się bez utraty danych.
1. **Bez długich myślników** w tekstach widocznych dla użytkownika (HTML, JS, komunikaty API): przecinek, kropka,
   dwukropek lub nawias; zakresy „5-6”. Placeholdery braku danych to „-”.
2. **Najlepszy wynik dnia.** `game_attempts.best` (MAX z liczby zgodności dziś, łącznie z próbami bonusowymi;
   wygrana = 10). `/api/game/me`, `/api/game/session` i `/api/game/roll` zwracają `best_today`. Po wyczerpaniu prób
   (`attempts_left==0` po rzucie, 429 albo wejście z 0 prób) ekran końcowy pokazuje „Twój najlepszy wynik dziś: X/10”
   i bębny ustawione na najlepszy rzut z tej wizyty (po przeładowaniu tylko liczba). Ostatni rzut nie jest wynikiem.
3. **+10 prób za wpisanie kodu ze stoiska (rejestrację dawcy), sumują się.** `game_sessions.bonus_attempts`, bonus
   nie wygasa o północy. Próby dostępne = (5 − zużyte dziennie) + bonus; rzut zużywa najpierw pulę dzienną, potem
   bonus (w jednej transakcji). API zwraca `attempts_left` (suma) i `bonus_attempts`. `/api/donor/register` używa
   opcjonalnej sesji gry albo tworzy nową (cookie + `token`), bonus w tej samej transakcji co zużycie kodu; odpowiedź
   ma `bonus_attempts_granted`, `attempts_left`, `play_path` ze świeżym tokenem QR.
4. **Nazewnictwo:** to nie jest rejestracja u nas (ta odbywa się na stoisku w bazie DKMS). Nav/przycisk „Wpisz kod
   ze stoiska”, h1 /potwierdz „Wpisz kod od wolontariusza”; URL /potwierdz bez zmian; bez form rodzajowych.
5. **Kod QR stoiska zmienia się co minutę.** `app/qrtoken.py`: `HMAC-SHA256(secret_key, "qr:<stoisko>:<minuta>")`,
   10 znaków base32; ważny bieżący i 2 poprzednie (ok. 2-3 min). `play_path = /graj?stoisko=<id>&t=<token>`.
   `POST /api/game/enter {booth_id,t}` zapisuje w sesji przepustkę (`pass_booth`, `pass_until` = +30 min; ponowne
   skanowanie odnawia). `/api/game/roll` wymaga ważnej przepustki dla stoiska, inaczej 403 „Zeskanuj ponownie kod
   QR ze stoiska.” (limit prób sprawdzany wcześniej, więc gracz bez prób dostaje 429). `/api/booth/{id}/state` zwraca
   `play_path` i `qr_seconds_left` tylko personelowi (admin albo wolontariusz tego stoiska); `/stoisko/<id>` wymaga
   więc zalogowania (inaczej link do /wolontariusz). Admin: „Otwórz ekran stoiska” i „Link do gry (ważny ~2 min)”.
   `reset-my-game` zeruje też bonus.
6. **Szansa na wygraną 1/300** (`game.WIN_ONE_IN`).
7. **Konta wolontariuszy zamiast PIN-u.** Tabela `volunteers(login, password_hash argon2, created_at)`, login
   `^[a-z0-9._-]{3,32}$`, hasło min. 8 znaków (puste = losowe 12 znaków bez 0/O/1/l/I; jawne tylko w odpowiedzi na
   utworzenie/reset). `POST /api/volunteer/auth {login,password,booth_id,cf_turnstile}` (throttle per login),
   stoisko wybierane przy logowaniu (`GET /api/booths`, publiczna lista id+nazwa). Cookie `{role,booth,login,ph}`:
   reset hasła lub usunięcie konta wylogowuje. Kolumna `booths.pin_hash` zostaje (wpisywany hash losowego sekretu).
   `BOOTSTRAP_BOOTHS` przyjmuje `id:nazwa:pin` (pin ignorowany) i `id:nazwa`. Admin API: `GET/POST /api/admin/volunteers`,
   `POST .../{login}/reset-password`, `DELETE .../{login}`; w UI gotowa wiadomość z przyciskiem „Kopiuj”.
8. **Wydziały:** etykieta „Wx - Wydział ...” (wyjątek: „Inne”), kolejność jak w słowniku (remisy w rankingu też wg
   słownika). Pozycja `INNE` / „Inne” zawsze na końcu (seed, migracja, `PUT /api/admin/dictionary`).
9. **Logo Helpers' Generation i Samorządu Studenckiego:** prawdziwe logo HG (`helpers-generation-logo.svg`, czerwone, 777.54×264.69)
   pokazywane jako białe wariant `-white.svg` na czerwonym tle (kafelek na stronie, pas na certyfikatach); logo Samorządu
   (`samorzad-studencki.svg`, 221.3×60.9) w headerze (≥992px), stopce, pasku stoiska i w nagłówku certyfikatów (cert.js).
10. **Dawca faktyczny (legitymacja Dawcy Przeszczepu / Zasłużonego Dawcy Przeszczepu).** Wolontariusz przy generowaniu
    kodu wybiera typ `potential` (domyślny) albo `actual`; dla `actual` podaje numer legitymacji i datę wydania.
    Nie zapisujemy danych osobowych ani jawnego numeru czy daty, tylko
    `card_hash = HMAC-SHA256(secret_key, "card:" + numer_znormalizowany + "|" + data_iso)` (hex; numer: trim, bez
    spacji i myślników, uppercase, 1-40 znaków). Tabele/kolumny: `registration_codes.kind` + `card_hash`,
    `actual_donor_cards(card_hash PK, registered_date)`, `donors_stats.kind`. Blokada podwójnej rejestracji: 409 przy
    generowaniu, gdy hash jest w `actual_donor_cards` albo ma aktywny kod (wygasły/anulowany nie blokuje); przy
    rejestracji wstawienie do `actual_donor_cards` w tej samej transakcji, `IntegrityError` = 409. Bonus +20 prób
    (zamiast +10, sumuje się). `check-code` zwraca `kind`. Statystyki: per wydział `potential`/`actual`/`total`
    (`count` = total), wykres skumulowany (czerwony #e2001a + granat #2c5a82) z legendą i tabelą; panel wolontariusza
    rozbija liczniki. CSV ma kolumnę `kind`. `wipe` czyści też `actual_donor_cards`. Certyfikat dawcy faktycznego ma
    osobny tytuł i podziękowanie.
11. **/graj bez stoiska:** nagłówek „Podejdź do jednego ze stanowisk”, lista „C-13 - Budynek C-13, 3-7 listopada”,
    „Godziny: ...” i „Zeskanuj kod QR u wolontariusza.”; pusta lista „Terminy stanowisk wkrótce.”. `booths` dostaje
    `building`, `date_from`, `date_to`; godziny wspólne w `settings.booth_hours` (`GET/PUT /api/admin/booth-hours`).
    Publiczne `GET /api/booths/public` (building, name, daty, hours; bez genotypów i tokenów; bez stoisk po `date_to`;
    kolejność wg `date_from`, potem budynku). Daty formatuje frontend (`formatDateRange` w common.js).

12. **Losowanie finałowe i certyfikat gracza.** Framing gry: wzór stoiska należy do pacjenta czekającego na Dawcę,
    gracz sprawdza, czy to on jest jego bliźniakiem genetycznym (nie „szuka bliźniaka”). Po trafieniu 10/10 gracz dostaje
    certyfikat (canvas, tylko w przeglądarce) z wzorem (10 kształtów) i godziną trafienia do minuty w Europe/Warsaw
    (`formatWarsaw` w common.js, z czasu serwera, nie zegara przeglądarki); po przeładowaniu strony dane wracają z
    `/api/game/me`. Na koniec akcji admin losuje jeden genotyp spośród wszystkich prawdziwych trafień
    (`genotype_history.matched_at IS NOT NULL AND is_test=0`); zwycięzca potwierdza się certyfikatem (wzór + czas).
    Zapisywane jest wyłącznie anonimowe: wzór, stoisko, czas trafienia, `session_id` (losowy). Nick nigdy nie opuszcza telefonu.
    - `GET /api/admin/raffle` → `{entries_count, entries:[{genotype, booth_id, booth_name, matched_at}], draws:[{genotype, drawn_at, booth_id, matched_at}]}`
    - `POST /api/admin/raffle/draw` → `{genotype, drawn_at, booth_id, booth_name, matched_at, remaining}`; losuje `secrets.choice`
      spośród jeszcze niewylosowanych (ponowne losowanie, gdy zwycięzca się nie zgłosi); 409 „Brak trafień do wylosowania.”
    - Admin: sekcja „Losowanie finałowe” (przycisk z potwierdzeniem, wynik jako kształty, historia losowań, lista wszystkich trafień).
    - `reset-my-game` zeruje też `won_genotype/won_at` sesji; `wipe` czyści `raffle_draws`.

---
## Iteracja 4 (nadpisuje wcześniejsze punkty; 2026-10-31)
Ogólne: migracje idempotentne w `db._migrate`, baza prod zachowuje dane. Bez długich myślników w UI. Ikony tylko Tabler.
Bez wymyślonych treści (mity o dawstwie, statystyki, adresy). Bez inline JS. Zmiany wizualne renderować i oglądać.
Punkt 1 „Twardych zasad” zostaje poza jednym: dochodzi pseudonimowy, dobowy klucz urządzenia (pkt 2) oraz strony prawne.

1. **Koniec losowania finałowego; każde 10/10 ma własny token.** Usunąć `routes/raffle.py`, sekcję admina, teksty o losowaniu,
   `test_raffle.py`, tabelę `raffle_draws` (`DROP TABLE IF EXISTS`). Nowa tabela
   `wins(token TEXT PK, seq INTEGER NOT NULL, genotype TEXT NOT NULL, booth_id TEXT NOT NULL, won_at TEXT NOT NULL, session_id TEXT NULL, is_test INTEGER NOT NULL DEFAULT 0)`.
   Token `HG-XXXX-XXXX` z alfabetu `volunteer.CODE_ALPHABET` (`secrets`, retry na kolizji). `seq` = kolejny numer prawdziwych
   trafień (w tej samej transakcji, `MAX(seq)+1` dla `is_test=0`), testowe mają `seq=0`. `db.record_win` tworzy wpis zawsze
   (także `force-win`). `game_sessions.won_token`. Migracja dopisuje `wins` dla istniejących `genotype_history.matched_at`
   (kolejność wg `matched_at`, z `is_test`, z sesją po `won_genotype`). `roll` dla wygranej i `game_state` zwracają
   `won_token, won_seq, won_booth_name, won_genotype, won_at`. `GET /api/admin/wins` → `{count, wins:[{seq,token,genotype,booth_id,booth_name,won_at}]}`
   (bez testowych, po `seq`). Admin: sekcja „Trafienia 10/10” (tabela, filtr po tokenie po stronie klienta).

2. **Limit: 5 prób dziennie na każdym stanowisku, liczony po hashu urządzenia.** Działa między przeglądarkami.
   - `static/fingerprint.js`: `deviceHash()` liczy SHA-256 (`crypto.subtle`) po stronie przeglądarki z sygnałów wspólnych dla
     przeglądarek jednego urządzenia: rodzina systemu + major iOS (z UA), `min/max(screen.width,height)`, `colorDepth`,
     `devicePixelRatio` (2 miejsca), `hardwareConcurrency`, `maxTouchPoints`, strefa czasowa. Bez canvasa, WebGL, audio, języka,
     pamięci (różnią się między przeglądarkami). Surowe wartości nie opuszczają przeglądarki.
   - Serwer: `POST /api/game/enter {booth_id,t,device,consent}`; `device` regex `^[0-9a-f]{64}$` (inaczej 422), `consent` musi być
     `true` (inaczej 422 „Zaakceptuj regulamin i politykę prywatności.”). Sesja zapisuje `consent_at` i
     `device_key = HMAC-SHA256(sól_dobowa, device)` (hex, 32 znaki). Surowego hasha nie zapisujemy.
   - **Sól dobowa:** `settings.device_salt` = JSON `{date,salt}`, nowa losowa przy pierwszym użyciu danego dnia (Europe/Warsaw); wtedy też
     `DELETE FROM booth_plays WHERE date<dziś` i `UPDATE game_sessions SET device_key=NULL`. Stara sól znika, więc klucza nie da się powiązać
     między dniami. Dlatego hash nie blokuje drugiej wygranej w innej przeglądarce (OK: każde 10/10 ma własny token).
   - Tabela `booth_plays(device_key, booth_id, date, session_id, attempts, PK(device_key,booth_id,date,session_id))`.
   - **Tolerancja kolizji** `settings.device_tolerance` (int 1..10, domyślnie 3): identyczne modele telefonów dają ten sam hash. Na klucz+stoisko+dzień:
     `pozostało = max(0, min(5 - moje_próby, 5*tolerancja - suma_prób_klucza))`. Przy 1 to twardy limit 5 na hash.
   - `_roll`: najpierw przepustka i `device_key` (brak = 403 „Zeskanuj ponownie...”), potem limit: pula stanowiska, potem bonus (bonus sesyjny bez zmian).
     429: „Limit prób na tym stanowisku na dziś wykorzystany. Zagraj na innym stanowisku albo wróć jutro.” `game_attempts` zostaje do `best` i podsumowań
     (zawsze upsert wiersza dnia; `attempts` rośnie przy każdym rzucie z puli dziennej).
   - `game_state`: gdy ważna przepustka, `attempts_left` = pula tego stanowiska + bonus; bez przepustki 5 + bonus. Dodatkowo `booth_left`.
   - `reset-my-game`: kasuje też `booth_plays` sesji i `won_token`; `wipe`: `booth_plays`, `wins`.

3. **Nagrody.** 6-10/10: drobny upominek na stanowisku (pokazanie wyniku wolontariuszowi, do wyczerpania zapasów). 10/10: certyfikat i komentarz
   obalający mit o dawstwie szpiku pod postem podsumowującym rejestracje z danego dnia na Facebooku Samorządu, z certyfikatem w załączniku.
   Link do Facebooka z `settings.facebook_url` (publicznie w `/api/config`); pusty = sam tekst, bez linku. `GET/PUT /api/admin/settings {device_tolerance, facebook_url}`
   (URL musi zaczynać się od `https://`).

4. **Bitwa Wydziałów** (`/bitwa`, osobno od `/statystyki`). `settings.faculty_students` = JSON `{source, counts:{kod:int}}`, seed z `app/seed_students.json` przy
   pierwszym starcie. `stats.battle(conn, date=None)` → `ranking:[{rank,code,name,registered,students,per_1000}]` (`per_1000 = round(total/students*1000,2)`, malejąco, remis: więcej
   rejestracji, potem kolejność słownika) i `unranked:[{code,name,registered}]` (bez liczby studentów oraz `INNE`). `GET /api/stats/battle` → `{ranking, unranked, source}`.
   `GET/PUT /api/admin/students {source, counts:{kod:int|null}}` (kody ze słownika, 1..100000, source do 500 zn.). Admin: formularz wydział + pole liczby + pole źródła.
   `/bitwa` pokazuje ranking wg przelicznika, liczby wejściowe, jawne źródło danych i metodę („rejestracje na 1000 studentów”). `/statystyki`: same liczby, bez rankingu bitwy.
   `admin/summary` dostaje `battle` (top 3 rankingu w zakresie); grafika social pokazuje „Bitwa Wydziałów” wg przelicznika, a gdy pusto, `podium`.

5. **`/login`: jeden panel dla wszystkich.** `login.html` + `login.js`; po zalogowaniu ta sama strona pokazuje funkcje wg rangi (sekcje z `admin.html` i `wolontariusz.html`
   scalone, tamte pliki usunięte; `admin.js`/`wolontariusz.js` eksportują `initAdmin()`/`initVolunteer(me)` bez własnego logowania). `/admin` i `/wolontariusz` → 302 na `/login`.
   - `volunteers.role` (`volunteer`|`admin`, domyślnie `volunteer`). Awaryjne konto: login `admin` + hasło `ADMIN_SECRET` (bez wiersza w bazie; login `admin` zastrzeżony).
   - `POST /api/auth/login {login,password,cf_turnstile}` → `{login,role,booth:null}`, `POST /api/auth/logout`, `GET /api/auth/me` → `{login,role,booth:{id,name}|null}`,
     `POST /api/auth/booth {booth_id}` ustawia stoisko w cookie. Zastępują `/api/volunteer/auth|logout`, `/api/admin/login|logout|me`. Throttle per login bez zmian.
   - Rola czytana z bazy przy każdym żądaniu (degradacja działa od razu, reset hasła wylogowuje). Wolontariusz bez stoiska: 409 „Wybierz stoisko.” przy akcjach na stoisku.
   - Admin: przy koncie wybór rangi, `PATCH /api/admin/volunteers/{login} {role}`; listy zwracają `role`.

6. **Certyfikaty i grafiki: jeden wygląd.** W `cert.js` wspólna `drawFrame` (tło z łagodnym wzorem, nagłówek, pasek partnerów, czerwony pas) używana przez certyfikat gracza 10/10,
   dawcy, dawcy faktycznego, nowy wynik gry i grafiki social. Wzór: kształty gry jako powtarzalny kafel, alfa ok. 0,05, nie może obniżać czytelności tekstu. Tytuł/akcent/treść w tym samym układzie, treść
   wyśrodkowana w pionie (bez stałych `y`). 10/10: token, „Trafienie nr N”, data i godzina, stanowisko, wzór. Bez wzmianki o losowaniu.
   **Partnerzy:** tabela `partners(id PK AUTOINCREMENT, name, filename)`, pliki w `$DATA_DIR/partners/`, serwowane `GET /partners/{plik}`. `GET /api/partners` publiczne → `[{id,name,url}]`.
   `POST /api/admin/partners {name, filename, data_base64}` (JSON, do 1,5 MB, png/jpg/webp/svg sprawdzane po sygnaturze; svg bez `<script`, `on*=`, `foreignObject`, `href` zewnętrznych, musi mieć `width`+`height`) ,
   `DELETE /api/admin/partners/{id}`. Admin: lista + formularz. Na grafikach pasek nad czerwonym pasem, tylko gdy są partnerzy; loga skalowane, by się zmieściły.

7. **Udostępnij.** `showDownload` obok „Pobierz” dodaje „Udostępnij” (`navigator.share` z plikiem PNG, gdy `navigator.canShare({files})`, inaczej brak przycisku; blob gotowy przed kliknięciem; `AbortError` ignorowany).
   Podpowiedź: „Udostępnij otwiera menu telefonu, wybierz np. Instagram lub Facebook. Obraz nie zapisuje się w galerii.”

8. **Wynik dla każdego gracza.** Po pierwszym rzucie dostępny przycisk „Odbierz swój wynik”: `renderResultCert({nick, best, boothName, date})` (9:16, ten sam `drawFrame`), zachęca do gry, pokazuje adres `/graj`, bez zmyślonych danych.
   Przy `best >= 6` ekran informuje o upominku na stanowisku; przy 10/10 instrukcja z pkt 3.

9. **Prawo.** Strony `/polityka-prywatnosci`, `/regulamin` (statyczny HTML). Znaczniki `{{OWNER}}`, `{{CONTACT}}` podstawiane w `_page` z env `LEGAL_OWNER`, `LEGAL_CONTACT` (`html.escape`), puste = „[do uzupełnienia]” + ostrzeżenie w logu.
   Linki w stopce każdej strony. `/graj`: przed pierwszym wejściem obowiązkowy checkbox „Akceptuję regulamin i politykę prywatności oraz zgadzam się na obliczenie identyfikatora urządzenia” (pamiętany w `localStorage.hp_consent`).
   Pisać „pseudonimowy”, nigdy „anonimowy” o kluczu urządzenia.

10. **Menu:** Graj, Wpisz kod ze stoiska, Bitwa Wydziałów, Statystyki. Stopka dodatkowo: Regulamin, Polityka prywatności, Logowanie. README i `.env.example` zaktualizować (role, prywatność, nowe env).

---
## Iteracja 5 (nadpisuje pkt 2 i 9 iteracji 4)
1. **Dwa klucze urządzenia.** `fingerprint.js` eksportuje `deviceHashes()` → `{base, ext}`. `base` bez zmian (sygnały z iteracji 4). `ext` = SHA-256 z `base` + sygnałów różnicujących egzemplarze
   tego samego modelu: wersja iOS major+minor z UA, `navigator.language`, `userAgentData.getHighEntropyValues(['model','platformVersion'])` (gdy dostępne), media queries (`prefers-reduced-motion`, `prefers-contrast`,
   `prefers-reduced-transparency`, `inverted-colors`, `forced-colors`, `color-gamut`, `dynamic-range`; BEZ `prefers-color-scheme`, zmienia się o zachodzie słońca), wsparcie najnowszych emoji (wersja czcionki systemu, szerokość w canvas `measureText`, tylko tak/nie na próbnych znakach), wykrycie czcionek
   (lista ok. 30 nazw: Samsung, Xiaomi, Huawei, Windows, macOS, iOS; porównanie `measureText` z czcionką zapasową, bez pikseli), lista głosów `speechSynthesis.getVoices()` (posortowane nazwy, czekaj na `voiceschanged` maks. 400 ms), `navigator.storage.estimate().quota`
   zaokrąglone do potęgi 2, WebGL `UNMASKED_RENDERER_WEBGL` i `MAX_TEXTURE_SIZE`. Każdy sygnał w `try/catch`, brak = pusty. Całość nie może trwać dłużej niż 800 ms. Bez pikseli canvas i audio. Surowe wartości nie opuszczają przeglądarki.
2. **Serwer.** `POST /api/game/enter` przyjmuje dodatkowo `device_ext` (ten sam regex, opcjonalne, brak = `device`). `game_sessions.device_ext_key`, `booth_plays.ext_key TEXT NOT NULL DEFAULT ''` (obie sole tą samą solą dobową, HMAC z innym prefiksem; rotacja zeruje też `device_ext_key`).
   `booth_pool`: `max(0, min(5 - max(moje_próby, suma_prób_ext_key), 5*tolerancja - suma_prób_device_key))`. `device_tolerance` domyślnie 10, zakres 1..50: to teraz sufit dla identycznych urządzeń, limit 5 trzyma `ext`. Przy 1: twardy limit 5 na klucz podstawowy jak dotąd.
   `GET /api/admin/settings` zwraca też `device_stats: {date, base_keys, ext_keys}` (liczby różnych kluczy dziś w `booth_plays`), panel pokazuje je w Ustawieniach, żeby ocenić kolizje na prawdziwych telefonach.
3. **Zgoda w oknie startowym.** Bez checkboxa i bez osobnej sekcji startu. Okno startowe (HLA, zasady) pokazuje się przed grą, gdy brak `hp_consent` albo brak sesji; zawiera widget Turnstile, zdanie „Naciskając przycisk, akceptujesz regulamin i politykę prywatności oraz zgadzasz się na obliczenie identyfikatora urządzenia.” z linkami
   i przycisk „Zaakceptuj i zagraj”, który zapisuje zgodę, tworzy sesję i wchodzi do gry. Okna nie da się zamknąć bez akceptacji (Esc zablokowany). „Zasady” otwiera je w trybie podglądu: bez zdania o zgodzie, przycisk „Zamknij”. `hp_intro` znika, wystarcza `hp_consent`.
4. **Strony prawne:** polityka pkt a: dwa klucze, rozszerzona lista parametrów (czcionki, głosy syntezy mowy, język, ustawienia dostępności, pojemność pamięci, układ graficzny, model), zgoda przyciskiem zamiast checkboxa. Regulamin: „Zgoda zaznaczona przed pierwszą grą” → akceptacja przyciskiem w oknie startowym.

---
## Iteracja 6: kod „Dodatkowe losy” (promocja w mediach)
Gracz pokazuje wolontariuszowi post (udostępniony wynik albo inny materiał promocyjny z oznaczeniem helpers_wroclaw i dkms_pl). Wolontariusz ocenia to sam, nic o poście nie zapisujemy (ani linku, ani konta).
- Nowa tabela `promo_codes(code PK, booth_id NOT NULL REFERENCES booths(id), status CHECK IN ('ACTIVE','USED','EXPIRED'), created_at, used_at NULL)`, bo `registration_codes.kind` ma CHECK, którego SQLite nie pozwala zmienić. Ten sam format kodu i TTL co kody rejestracyjne, unikalność względem obu tabel, `expire_codes` wygasza obie.
- `POST /api/volunteer/generate-code {kind:'promo'}` tworzy kod (bez karty, bez statystyk). Lista kodów w `/api/volunteer/me` i `/api/admin/codes` obejmuje też promo z `kind:'promo'`; anulowanie działa dla obu. `config.PROMO_BONUS = 5`.
- `/potwierdz` (ten sam jeden formularz na kod): `check-code` zwraca `kind:'promo'`, wtedy strona ukrywa wydział, rok i certyfikat dawcy. `POST /api/donor/redeem-promo {code, cf_turnstile}` w jednej transakcji zużywa kod i dodaje `bonus_attempts` (sesja albo nowa, jak `register`); błędy jak `register` (404, 410). Odpowiedź: `bonus_attempts_granted, attempts_left, token, booth_name, play_path`. Nie dotyka `donors_stats`, Bitwy ani liczników rejestracji. `register` z kodem promo = 404. `wipe` czyści `promo_codes`.
- Panel: przycisk „Dodatkowe losy” obok generowania kodu rejestracyjnego, z krótką instrukcją co sprawdzić; widoczny kod i QR jak dotąd.
- Gra: w zasadach i w oknie końcowym informacja: udostępnij wynik lub inny materiał, oznacz helpers_wroclaw i dkms_pl, pokaż post wolontariuszowi, dostaniesz kod na 5 dodatkowych prób. Regulamin: ten sam zapis w zasadach gry. Polityka: bez zapisu postu i konta.

