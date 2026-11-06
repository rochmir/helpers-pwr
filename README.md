# helpersi-pwr

Aplikacja na akcję rejestracji dawców szpiku (DKMS) na Politechnice Wrocławskiej: gra w dopasowywanie
genotypów przy stoiskach, kody rejestracyjne wydawane przez wolontariuszy, anonimowe statystyki wydziałów
oraz panel admina. Adres docelowy: https://helpers-pwr.rupary.pl. Specyfikacja techniczna: `PLAN.md`.

## Prywatność

**Zapisujemy:**
- stoiska (id, nazwa, budynek, terminy, aktualny genotyp, liczniki), konta wolontariuszy (login i hash hasła, pseudonimy),
- anonimowe sesje gry (losowy identyfikator, liczba prób na dzień, flaga „wygrał”),
- trafienia 10/10 do losowania finałowego: sam wzór genotypu i godzina trafienia (powiązane tylko z losowym identyfikatorem sesji) oraz wyniki losowania,
- kody rejestracyjne (kod, stoisko, status, czas utworzenia/użycia),
- statystykę dawców: stoisko, wydział, rok studiów i **sama data** rejestracji.

**Nie zapisujemy:**
- adresów IP (uvicorn z `--no-access-log`, brak logowania klienta, do Cloudflare Turnstile nie wysyłamy `remoteip`),
- imienia, nazwiska ani ksywki — do certyfikatów używane są wyłącznie w przeglądarce (canvas); na certyfikacie gracza widać wzór i godzinę trafienia, ale ksywka nie trafia na serwer,
- kodu ani godziny rejestracji w statystykach — wpisu nie da się powiązać z konkretną osobą ani kodem.

## Role

| Możliwość | Wolontariusz (konto: login + hasło) | Admin (`ADMIN_SECRET`) |
|---|---|---|
| Generowanie / anulowanie kodów | tylko swoje stoisko | każde stoisko |
| Liczniki i lista kodów | tylko swoje stoisko | wszystkie stoiska |
| Stoiska: dodawanie, usuwanie, zmiana nazwy, terminy, konta wolontariuszy, reset genotypu | nie | tak |
| Słownik wydziałów | nie | tak |
| Podsumowania dnia / całości, eksport CSV, grafiki | nie | tak |
| Statystyki na żywo (`/statystyki`) | publiczne | publiczne |

Reset hasła lub usunięcie konta wylogowuje wolontariusza. Po 10 błędnych logowaniach w 10 minut logowanie na dany login
jest blokowane na 5 minut (licznik per login, nie per IP, eduroam). Konta zakłada admin w panelu (pseudonimy, bez imion i nazwisk).

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
2. W `.env` uzupełnij `ADMIN_SECRET` (długi, losowy), `TURNSTILE_*` (patrz niżej).
   Opcjonalnie `BOOTSTRAP_BOOTHS=c13:Budynek C-13,w4:Budynek W-4` (`id:Nazwa`; stary format `id:Nazwa:PIN` też działa,
   PIN jest ignorowany) utworzy przy starcie brakujące stoiska; potem usuń tę linię.
3. `docker compose pull && docker compose up -d` — aplikacja nasłuchuje na `127.0.0.1:8010`, dane w `./data`.
4. Cloudflare, tunel:
   Zero Trust → Networks → Tunnels → istniejący tunel → Public Hostname → dodaj `helpers-pwr.rupary.pl`
   → usługa `http://localhost:8010`.
5. Cloudflare, captcha: Turnstile → Add widget → domena `helpers-pwr.rupary.pl` → klucze (site key i secret key)
   do `.env` (`TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`), potem `docker compose up -d`.
6. Wejdź na `/admin`, **zweryfikuj słownik wydziałów** (seed w `app/seed_dictionary.json` jest tylko
   punktem wyjścia), dodaj stoiska i konta wolontariuszy.

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
Panel `/admin`: hasło `dev`. Captcha jest wyłączona, ciasteczka bez HTTPS. Katalog `app/` jest podpięty tylko do odczytu
z live reloadem: zmiany w HTML, CSS, JS i Pythonie widać po odświeżeniu, bez przebudowy obrazu (statyki bez cache'u,
`DEV_NO_CACHE=1`). Zmiany w `requirements.txt` lub `Dockerfile` wymagają ponownego `up --build`. Dane trafiają do wolumenu
`helpers-lokalne-dane`; usuniesz je przez `docker compose -f docker-compose.local.yml down -v`.

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
(Windows: ustaw te zmienne w `$env:`). Bez kluczy Turnstile captcha jest wyłączona (w logu pojawia się ostrzeżenie).
