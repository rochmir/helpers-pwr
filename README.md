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

## Pierwsze wdrożenie

1. `cp .env.example .env`, uzupełnij `ADMIN_SECRET` (długi, losowy), `TURNSTILE_*` (patrz niżej).
   Opcjonalnie `BOOTSTRAP_BOOTHS=c13:Budynek C-13,w4:Budynek W-4` (`id:Nazwa`; stary format `id:Nazwa:PIN` też działa,
   PIN jest ignorowany) utworzy przy starcie brakujące stoiska; potem usuń tę linię.
2. `docker compose up -d --build` — aplikacja nasłuchuje na `127.0.0.1:8010`, dane w `./data`.
3. Cloudflare, tunel:
   Zero Trust → Networks → Tunnels → istniejący tunel → Public Hostname → dodaj `helpers-pwr.rupary.pl`
   → usługa `http://localhost:8010`.
4. Cloudflare, captcha: Turnstile → Add widget → domena `helpers-pwr.rupary.pl` → klucze (site key i secret key)
   do `.env` (`TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`), potem `docker compose up -d`.
5. Wejdź na `/admin`, **zweryfikuj słownik wydziałów** (seed w `app/seed_dictionary.json` jest tylko
   punktem wyjścia), dodaj stoiska i konta wolontariuszy.

## Uruchomienie lokalne i testy

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ADMIN_SECRET=dev COOKIE_SECURE=0 DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/pytest -q
```

Bez kluczy Turnstile captcha jest wyłączona (w logu pojawia się ostrzeżenie).
