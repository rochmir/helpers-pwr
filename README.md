# helpersi-pwr

Aplikacja na akcję rejestracji dawców szpiku (DKMS) na Politechnice Wrocławskiej: symulator HLA „HLA Match Maker – Sprawdź Parametry”
i towarzyszący konkurs, dynamiczne kody QR (ważne 60 s) pokazywane przez wolontariuszy do głosu w Pucharze Dawcy PWr, statystyki, Puchar oraz wspólny panel personelu.
Reguły wynikają z dwóch regulaminów (do wglądu na `/dokumenty`). Adres docelowy: https://helpers-pwr.rupary.pl. Specyfikacja techniczna: `PLAN.md`.

## Prywatność

**Zapisujemy:**
- stoiska (id, nazwa, budynek, terminy, aktualny genotyp, liczniki), konta personelu (login, hash hasła, ranga; pseudonimy),
- sesje symulatora (losowy identyfikator, liczba prób na dzień, flaga „wygrał”, czas zgody, token i wzór własnego trafienia do odtworzenia certyfikatu),
- trafienia 10/10 (Token Losu `HG-XXXX-XXXX`): token, znacznik czasu, wzór, stoisko, numer porządkowy i czas oznaczenia jako wykorzystany. Bez powiązania z sesją (`wins.session_id` jest NULL),
- sesje symulatora (losowy identyfikator w ciasteczku `hp_game`, liczba prób na dzień i stanowisko w `booth_plays`, flaga „wygrał”, czas zgody, dodatkowe próby,
  flaga „oddał głos” `cup_voted`, tymczasowy claim kodu QR na 10 minut, data odebrania bonusu „post”, token i wzór własnego trafienia do odtworzenia certyfikatu),
- głosy w Pucharze (`donors_stats`): wydział, kategoria (nowy / zarejestrowany / faktyczny), rok studiów, stoisko i znacznik czasu. **Bez powiązania z sesją**, bez urządzenia, bez danych osobowych,
- kodów QR **nie zapisujemy**: token jest bezstanowy (podpisany HMAC identyfikator stoiska, kategoria i czas wygenerowania, ważny 60 s),
- historyczne tabele `registration_codes` i `promo_codes` (z wersji sprzed v3) zostają w starszych bazach, ale nic w nie nie piszemy; czyści je tylko „wipe” w narzędziach testowych,
- dokumenty prawne (treść, wersje), partnerów (nazwa i plik logo w `DATA_DIR/partners`).

**Nie zapisujemy:**
- adresów IP (uvicorn z `--no-access-log`),
- imienia, nazwiska ani ksywki (certyfikaty rysuje przeglądarka), numeru ani daty legitymacji (wolontariusz ją tylko ogląda),
- odcisku urządzenia (fingerprintingu): limit prób opiera się wyłącznie na losowym identyfikatorze sesji w ciasteczku.

## Dokumenty prawne

Treści regulaminów i polityki prywatności są w bazie (`legal_documents`) i edytuje się je w panelu `/login`, sekcja „Regulaminy i dokumenty”, bez deployu.
Markdown jest renderowany na serwerze bez surowego HTML. Pliki w `app/legal/*.md` służą do seedu brakujących dokumentów bazowych oraz do jednorazowego podniesienia
dokumentów w istniejącej bazie do treści v3 (`settings.legal_seed_version`; stara treść trafia do historii wersji jako „system”, wersja +1, więc symulator poprosi o ponowną zgodę;
późniejsze edycje z panelu nie są nadpisywane).
Zmiana tytułu lub treści zwiększa wersję i ustawia datę ostatniej zmiany (tylko serwer), stan sprzed zmiany trafia do historii wersji.
Publicznie: `/dokumenty`, `/dokumenty/{slug}`. Miejsce `{{CONTACT}}` w treści zastępuje `LEGAL_CONTACT` (puste = „[do uzupełnienia]”). `LEGAL_OWNER` już nie istnieje.
Zmiana regulaminu konkursu lub polityki prywatności wymusza ponowną zgodę w symulatorze.

## Role

Jeden panel `/login` dla wszystkich (`/admin` i `/wolontariusz` przekierowują na `/login`); funkcje zależą od rangi konta.
Ranga jest czytana z bazy przy każdym żądaniu, więc degradacja i reset hasła działają od razu.

| Możliwość | Wolontariusz | Admin |
|---|---|---|
| Wybór stoiska po zalogowaniu | tak | tak |
| Kod QR do Pucharu (4 kategorie: nowy, zarejestrowany, faktyczny, post) | tylko wybrane stoisko | każde stoisko |
| Ekran stoiska `/stoisko/{id}` (wymaga zalogowania; bez sesji przekierowanie na `/login?next=...`) | tak | tak |
| Liczniki głosów | tylko wybrane stoisko | wszystkie stoiska |
| Stoiska, konta i rangi, słownik wydziałów, liczby studentów, partnerzy (kolejność strzałkami), ustawienia i terminy | nie | tak |
| Trafienia 10/10, weryfikacja Tokenu Losu, dokumenty prawne, podsumowania, eksport CSV, grafiki | nie | tak |
| Statystyki (`/statystyki`) i Puchar Dawcy PWr (`/puchar`) | publiczne | publiczne |

Konta zakłada admin w panelu. Awaryjne konto: login `admin` + hasło `ADMIN_SECRET` (bez wiersza w bazie, login zastrzeżony;
zmiana `ADMIN_SECRET` wylogowuje). Reset hasła lub usunięcie konta wylogowuje użytkownika. Po 10 błędnych logowaniach w 10 minut
logowanie na dany login jest blokowane na 5 minut (licznik per login, nie per IP, eduroam).

## Limit prób

5 prób na dobę na sesję (ciasteczko `hp_game`) na każdym stoisku (regulamin konkursu §4.2), tabela `booth_plays(session_id, booth_id, date)`; po zmianie doby (Europe/Warsaw) pula wraca.
Dodatkowe próby idą ponad pulę stoiska i nie wygasają o północy: głos nowy / zarejestrowany +10, faktyczny +20, „post” +5 (raz dziennie na sesję, także po terminie Pucharu).
Sesja jest tylko w ciasteczku (nagłówek `X-Game-Token` i kopia w `localStorage` zostały usunięte); stare ciasteczka nadal działają. Nie ma już `device_tolerance`.

## Stanowisko „Zajęcia”

Stoisko `zajecia` (`booths.is_lecture=1`, tworzone przy starcie) służy do promocji na wykładach, także przed akcją. Nie ma wolontariusza (kod QR Pucharu: 409,
usunięcie: 409), nie ma go w publicznych wykazach, a gra działa na nim bez ograniczenia datami. Prowadzący otwiera na ekranie sali statyczny link
`/zajecia/{token}` (rotujący QR, bez logowania). Link bierzesz w panelu admina, sekcja „Stoiska”: pole „Zajęcia: link dla prowadzących”, przycisk „Kopiuj link”;
„Wygeneruj nowy link” unieważnia poprzedni (token w `settings.lecture_screen_token`).

## Konkurs i Token Losu

Wynik 10/10 daje Token Losu na certyfikacie. Zgłoszenia (hasło + certyfikat) idą komentarzem na Facebooku Samorządu (`facebook_url`, domyślnie profil @samorzadpwr).
Komisja w panelu (sekcja „Weryfikacja Tokenu Losu”) sprawdza token (istnieje, wzór i data, nie był użyty) i oznacza go jako wykorzystany (`POST /api/admin/tokens/{token}/submit`, drugi raz 409; `unsubmit` cofa pomyłkę).
Po `CONTEST_DEADLINE` ekran 10/10 pokazuje, że zgłoszenia są zamknięte.

## Puchar Dawcy PWr

Wolontariusz po weryfikacji wybiera w panelu `/login` kategorię (nowy dawca, zarejestrowany dawca, faktyczny dawca lub „post / story”), klika „Pokaż kod QR” i pokazuje go osobie na jej telefonie.
Kod (`/potwierdz?t=...`) odświeża się co 60 s i jest ważny 60 s (serwer dodaje 5 s tolerancji); można go zeskanować kilka razy w tym czasie. Po terminie: „Kod wygasł. Podejdź do stanowiska po nowy kod”.
Skan = `POST /api/cup/claim` (sesja dostaje claim na 10 minut), potem `POST /api/cup/vote` z wydziałem i rokiem studiów. Jeden głos na sesję (drugi: 409). Kategoria „post” daje od razu +5 prób (raz dziennie), bez głosu.
Publiczny ekran `/stoisko/{id}` (kod QR do gry) wymaga zalogowania personelu.
Ranking `/puchar`: Wskaźnik Zaangażowania `WZ = LD / LS * 100` (LD = suma trzech równorzędnych kategorii, LS liczba studentów wpisana przez admina, `GET/PUT /api/admin/students`), remis decyduje LD.
Wydziały bez LS oraz „Inne” są poza klasyfikacją. Po terminie Pucharu skan kodu głosu, głos i kod QR w panelu zwracają 410 (kategoria „post” działa dalej).
Oficjalne wyniki: 16 grudnia 2026 (Wigilia Aktywnych Studentów, C-18).

Terminy (czas Europe/Warsaw): `CUP_DEADLINE` (domyślnie 2026-12-11T16:30) i `CONTEST_DEADLINE` (domyślnie 2026-12-11T16:00) można ustawić w `.env`,
a **w panelu admina** (sekcja „Ustawienia”) wpisać nową datę i godzinę dla obu terminów: „Koniec zliczania punktów Pucharu Dawcy PWr” i „Koniec przyjmowania zgłoszeń do konkursu HLA”.
Wartość z panelu (`settings.cup_deadline`, `settings.contest_deadline`) ma pierwszeństwo przed `.env`; puste pole przywraca domyślną. Zmiana działa od razu (bez restartu), także w komunikatach i w `/api/config`.
Daty wpisane na stałe w treści regulaminów nie zmieniają się automatycznie.

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
Panel `/login`: login `admin`, hasło `dev`. Ciasteczka bez HTTPS.
Test na telefonie w tej samej sieci Wi-Fi: uruchom z `PUBLIC_URL=http://<adres IP komputera>:8000` (np. `$env:PUBLIC_URL='http://192.168.0.10:8000'; .\lokalnie.ps1`),
bo kody QR kierują na `PUBLIC_URL`. Certyfikaty i kody QR warto sprawdzić na prawdziwym iPhonie i Androidzie. Katalog `app/` jest podpięty tylko do odczytu
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
