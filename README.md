# helpersi-pwr

Aplikacja na akcję rejestracji dawców szpiku (DKMS) na Politechnice Wrocławskiej: symulator HLA „HLA Match Maker – Sprawdź Parametry”
i towarzyszący konkurs, tokeny rejestracyjne (kody OTP) wydawane przez wolontariuszy, statystyki, Puchar Dawcy PWr oraz wspólny panel personelu.
Reguły wynikają z dwóch regulaminów (do wglądu na `/dokumenty`). Adres docelowy: https://helpers-pwr.rupary.pl. Specyfikacja techniczna: `PLAN.md`.

## Prywatność

**Zapisujemy:**
- stoiska (id, nazwa, budynek, terminy, aktualny genotyp, liczniki), konta personelu (login, hash hasła, ranga; pseudonimy),
- sesje symulatora (losowy identyfikator, liczba prób na dzień, flaga „wygrał”, czas zgody, token i wzór własnego trafienia do odtworzenia certyfikatu),
- trafienia 10/10 (Token Losu `HG-XXXX-XXXX`): token, znacznik czasu, wzór, stoisko, numer porządkowy i czas oznaczenia jako wykorzystany. Bez powiązania z sesją (`wins.session_id` jest NULL),
- **pseudonimowy, dobowy klucz urządzenia** (limit 5 prób na dobę na urządzenie): `HMAC(sól dobowa, hash)` skrótów z przeglądarki (`device_key`, `device_ext_key`)
  i liczniki prób. Sól jest losowa na każdy dzień (Europe/Warsaw) i rotowana zadaniem w tle co godzinę: po zmianie dnia stare `booth_plays` są kasowane,
  a klucze w sesjach zerowane. Dlatego „pseudonimowy”, nie „anonimowy”,
- tokeny rejestracyjne (kod, stoisko, typ: nowy dawca / dawca faktyczny, status, czasy; tabela `registration_codes`),
- punkty Pucharu (`donors_stats`): wydział, znacznik czasu i **stały** skrót urządzenia `HMAC(SECRET_KEY, "cup:"+device_ext)` (jeden głos z urządzenia). Bez roku studiów, stoiska, typu, tokenu i numeru legitymacji. Skrót trzymamy do końca audytu,
- dokumenty prawne (treść, wersje), partnerów (nazwa i plik logo w `DATA_DIR/partners`).

**Nie zapisujemy:**
- adresów IP (uvicorn z `--no-access-log`),
- imienia, nazwiska ani ksywki (certyfikaty rysuje przeglądarka), numeru ani daty legitymacji (wolontariusz ją tylko ogląda).

## Dokumenty prawne

Treści regulaminów i polityki prywatności są w bazie (`legal_documents`) i edytuje się je w panelu `/login`, sekcja „Regulaminy i dokumenty”, bez deployu.
Markdown jest renderowany na serwerze bez surowego HTML. Pliki w `app/legal/*.md` służą tylko do jednorazowego seedu brakujących dokumentów bazowych.
Zmiana tytułu lub treści zwiększa wersję i ustawia datę ostatniej zmiany (tylko serwer), stan sprzed zmiany trafia do historii wersji.
Publicznie: `/dokumenty`, `/dokumenty/{slug}`. Miejsce `{{CONTACT}}` w treści zastępuje `LEGAL_CONTACT` (puste = „[do uzupełnienia]”). `LEGAL_OWNER` już nie istnieje.
Zmiana regulaminu konkursu lub polityki prywatności wymusza ponowną zgodę w symulatorze.

## Role

Jeden panel `/login` dla wszystkich (`/admin` i `/wolontariusz` przekierowują na `/login`); funkcje zależą od rangi konta.
Ranga jest czytana z bazy przy każdym żądaniu, więc degradacja i reset hasła działają od razu.

| Możliwość | Wolontariusz | Admin |
|---|---|---|
| Wybór stoiska po zalogowaniu | tak | tak |
| Generowanie / anulowanie kodów | tylko wybrane stoisko | każde stoisko |
| Liczniki i lista kodów | tylko wybrane stoisko | wszystkie stoiska |
| Stoiska, konta i rangi, słownik wydziałów, liczby studentów, partnerzy, ustawienia | nie | tak |
| Trafienia 10/10, weryfikacja Tokenu Losu, dokumenty prawne, podsumowania, eksport CSV, grafiki | nie | tak |
| Statystyki (`/statystyki`) i Puchar Dawcy PWr (`/puchar`) | publiczne | publiczne |

Konta zakłada admin w panelu. Awaryjne konto: login `admin` + hasło `ADMIN_SECRET` (bez wiersza w bazie, login zastrzeżony;
zmiana `ADMIN_SECRET` wylogowuje). Reset hasła lub usunięcie konta wylogowuje użytkownika. Po 10 błędnych logowaniach w 10 minut
logowanie na dany login jest blokowane na 5 minut (licznik per login, nie per IP, eduroam).

## Limit prób

5 prób na dobę na urządzenie na każdym stoisku (regulamin konkursu §4.2 ust. 2), liczone po kluczu urządzenia (działa między przeglądarkami tego samego telefonu).
Limit 5 trzyma klucz rozszerzony; identyczne modele telefonów dają ten sam klucz podstawowy, więc `settings.device_tolerance` (1-50, domyślnie 10) to sufit
`5 * tolerancja` prób łącznie na klucz podstawowy. Dodatkowe próby (kod za post/story, głos w Pucharze) idą ponad pulę stoiska i nie wygasają o północy. Po zmianie dnia klucz znika, więc trzeba ponownie zeskanować kod QR ze stoiska.

## Stanowisko „Zajęcia”

Stoisko `zajecia` (`booths.is_lecture=1`, tworzone przy starcie) służy do promocji na wykładach, także przed akcją. Nie ma wolontariusza (tokeny i kody: 409,
usunięcie: 409), nie ma go w publicznych wykazach, a gra działa na nim bez ograniczenia datami. Prowadzący otwiera na ekranie sali statyczny link
`/zajecia/{token}` (rotujący QR, bez logowania). Link bierzesz w panelu admina, sekcja „Stoiska”: pole „Zajęcia: link dla prowadzących”, przycisk „Kopiuj link”;
„Wygeneruj nowy link” unieważnia poprzedni (token w `settings.lecture_screen_token`).

## Konkurs i Token Losu

Wynik 10/10 daje Token Losu na certyfikacie. Zgłoszenia (hasło + certyfikat) idą komentarzem na Facebooku Samorządu (`facebook_url`, domyślnie profil @samorzadpwr).
Komisja w panelu (sekcja „Weryfikacja Tokenu Losu”) sprawdza token (istnieje, wzór i data, nie był użyty) i oznacza go jako wykorzystany (`POST /api/admin/tokens/{token}/submit`, drugi raz 409; `unsubmit` cofa pomyłkę).
Po `CONTEST_DEADLINE` ekran 10/10 pokazuje, że zgłoszenia są zamknięte.

## Puchar Dawcy PWr

Wolontariusz po weryfikacji generuje token rejestracyjny (kod OTP; typ „Nowy dawca” albo „Dawca faktyczny”, legitymację tylko ogląda). Student wpisuje go na `/potwierdz`
(`/graj` i `/potwierdz` zostają jako adresy kodów QR), wybiera wydział i oddaje jeden głos z urządzenia (drugi głos = 409, token wtedy nie jest zużywany).
Ranking `/puchar`: Wskaźnik Zaangażowania `WZ = LD / LS * 100` (LD punkty, LS liczba studentów wpisana przez admina, `GET/PUT /api/admin/students`), remis decyduje LD.
Wydziały bez LS oraz „Inne” są poza klasyfikacją. Po `CUP_DEADLINE` rejestracja punktów i generowanie tokenów zwracają 410.

Terminy (czas Europe/Warsaw, nadpisywane w `.env`): `CUP_DEADLINE` (domyślnie 2026-12-11T16:30), `CONTEST_DEADLINE` (domyślnie 2026-12-11T16:00).

## Jak powstaje obraz

Push do gałęzi `main` ze zmianami w `app/`, `Dockerfile`, `requirements.txt`, `.dockerignore` lub w workflow uruchamia
`.github/workflows/helpers-pwr.yml`. Najpierw przechodzą testy (`pytest -q`), potem budowany jest obraz
(`linux/amd64` i `linux/arm64`) i wysyłany do GHCR jako `ghcr.io/rochmir/helpers-pwr` z tagami `latest` i `sha-<skrót>`.
Workflow można też odpalić ręcznie (`workflow_dispatch`).

## Jednorazowa konfiguracja GHCR

Wybierz jedno:

- **Pakiet publiczny:** GitHub, Packages, `helpers-pwr`, Package settings, Change visibility, Public. Serwer pobiera obraz bez logowania.
- **Pakiet prywatny:** na serwerze `docker login ghcr.io -u rochmir` i jako hasło token PAT z uprawnieniem `read:packages`.

## Pierwsze wdrożenie

Repozytorium na serwerze nie jest potrzebne, wystarczą `docker-compose.yml` i `.env`.

1. Katalog i pliki (dla prywatnego repozytorium `curl` nie zadziała: skopiuj pliki ręcznie, np. `scp`):
   ```bash
   mkdir -p ~/helpers-pwr && cd ~/helpers-pwr
   curl -fsSLO https://raw.githubusercontent.com/rochmir/helpers-pwr/main/docker-compose.yml
   curl -fsSLO https://raw.githubusercontent.com/rochmir/helpers-pwr/main/.env.example
   cp .env.example .env
   mkdir -p data && sudo chown 10001 data
   ```
2. W `.env` uzupełnij `ADMIN_SECRET` (długi, losowy) i `LEGAL_CONTACT` (kontakt w dokumentach prawnych).
   Opcjonalnie `BOOTSTRAP_BOOTHS=c13:Budynek C-13,w4:Budynek W-4` (`id:Nazwa`; stary format `id:Nazwa:PIN` też działa,
   PIN jest ignorowany) utworzy przy starcie brakujące stoiska; potem usuń tę linię.
3. `docker compose pull && docker compose up -d` — aplikacja nasłuchuje na `127.0.0.1:8010`, dane w `./data`.
4. Cloudflare, tunel:
   Zero Trust → Networks → Tunnels → istniejący tunel → Public Hostname → dodaj `helpers-pwr.rupary.pl`
   → usługa `http://localhost:8010`.
5. Wejdź na `/login` (login `admin`, hasło `ADMIN_SECRET`), **zweryfikuj słownik wydziałów** (seed w `app/seed_dictionary.json` jest tylko
   punktem wyjścia), dodaj stoiska i konta wolontariuszy, wpisz liczby studentów (stan na 30 listopada 2026, Centrum Kształcenia) do Pucharu Dawcy PWr i sprawdź link do Facebooka w ustawieniach.

## Aktualizacja

```bash
docker compose pull && docker compose up -d
```

Cofnięcie wersji: w `docker-compose.yml` zmień tag `latest` na wybrany `sha-xxxxxxx` (lista tagów w GitHub, Packages, `helpers-pwr`)
i uruchom `docker compose up -d`.

## Migracja z obecnego wdrożenia

Dziś serwer ma sklonowane repozytorium z `./data` i `.env`. W tym samym katalogu:

1. Podmień `docker-compose.yml` na nowy (z repozytorium, `curl` jak wyżej albo `scp`).
2. `docker compose pull && docker compose up -d`. Dane zostają w `./data`, `.env` bez zmian.
3. Potem resztę plików repozytorium możesz usunąć, zostawiając `data/`, `.env` i `docker-compose.yml`.
4. Stary, zbudowany lokalnie obraz: `docker image rm helpersi-pwr`.

## Test lokalny w Dockerze

Wymagany jest tylko Docker. W katalogu repozytorium:

```bash
./lokalnie.sh          # Windows: .\lokalnie.ps1
```

To samo co `docker compose -f docker-compose.local.yml up --build`. Strona: `http://localhost:8000` (inny port: zmienna `HELPERS_PORT`).
Panel `/login`: login `admin`, hasło `dev`. Ciasteczka bez HTTPS. Katalog `app/` jest podpięty tylko do odczytu
z live reloadem: zmiany w HTML, CSS, JS i Pythonie widać po odświeżeniu, bez przebudowy obrazu (statyki bez cache'u,
`DEV_NO_CACHE=1`). Zmiany w `requirements.txt` lub `Dockerfile` wymagają ponownego `up --build`. Dane trafiają do folderu
`data-lokalne/` obok projektu (ignorowany przez git); żeby zacząć od zera, zatrzymaj kontener i usuń ten folder.

## Testy bez Dockera

Linux/macOS:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Windows:

```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

Uruchomienie bez Dockera: `ADMIN_SECRET=dev COOKIE_SECURE=0 DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8000`
(Windows: ustaw te zmienne w `$env:`).
