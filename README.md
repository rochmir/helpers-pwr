# helpersi-pwr

Aplikacja na akcję rejestracji dawców szpiku (DKMS) na Politechnice Wrocławskiej: gra w dopasowywanie
genotypów przy stoiskach, kody rejestracyjne wydawane przez wolontariuszy, statystyki wydziałów
i Bitwę Wydziałów oraz wspólny panel personelu. Adres docelowy: https://helpers-pwr.rupary.pl. Specyfikacja techniczna: `PLAN.md`.

## Prywatność

**Zapisujemy:**
- stoiska (id, nazwa, budynek, terminy, aktualny genotyp, liczniki), konta personelu (login, hash hasła, ranga; pseudonimy),
- sesje gry (losowy identyfikator, liczba prób na dzień, flaga „wygrał”, czas zgody na regulamin),
- trafienia 10/10: token `HG-XXXX-XXXX`, numer trafienia, wzór genotypu, stoisko i godzina (powiązane tylko z losowym identyfikatorem sesji),
- **pseudonimowy, dobowy klucz urządzenia** (limit 5 prób na stanowisko): przeglądarka liczy SHA-256 z kilku cech urządzenia
  (rodzina systemu, rozmiar ekranu, strefa czasowa itp.) i drugi, rozszerzony o cechy odróżniające egzemplarze tego samego modelu,
  a serwer zapisuje tylko `HMAC(sól dobowa, hash)` obu (`device_key`, `device_ext_key`) i liczbę prób na stanowisku. Surowych
  hashy nie zapisujemy. Sól jest losowa na każdy dzień (Europe/Warsaw) i rotowana także bez ruchu
  (zadanie w tle co godzinę): po zmianie dnia stare wpisy `booth_plays` są kasowane, a klucze w sesjach zerowane, więc klucza
  nie da się powiązać między dniami. Dlatego piszemy „pseudonimowy”, nie „anonimowy”,
- kody rejestracyjne i kody „Dodatkowe losy” (kod, stoisko, status, czas utworzenia/użycia; tabele `registration_codes` i `promo_codes`),
- statystykę dawców: stoisko, wydział, rok studiów i **sama data** rejestracji,
- partnerów (nazwa i plik logo w `DATA_DIR/partners`).

**Nie zapisujemy:**
- adresów IP (uvicorn z `--no-access-log`, brak logowania klienta, do Cloudflare Turnstile nie wysyłamy `remoteip`),
- imienia, nazwiska ani ksywki: do certyfikatów używane są wyłącznie w przeglądarce (canvas),
- kodu ani godziny rejestracji w statystykach: wpisu nie da się powiązać z konkretną osobą ani kodem.

Strony `/regulamin` i `/polityka-prywatnosci` podstawiają `{{OWNER}}` i `{{CONTACT}}` z `LEGAL_OWNER` i `LEGAL_CONTACT`
(puste = „[do uzupełnienia]” i ostrzeżenie w logu).

## Role

Jeden panel `/login` dla wszystkich (`/admin` i `/wolontariusz` przekierowują na `/login`); funkcje zależą od rangi konta.
Ranga jest czytana z bazy przy każdym żądaniu, więc degradacja i reset hasła działają od razu.

| Możliwość | Wolontariusz | Admin |
|---|---|---|
| Wybór stoiska po zalogowaniu | tak | tak |
| Generowanie / anulowanie kodów | tylko wybrane stoisko | każde stoisko |
| Liczniki i lista kodów | tylko wybrane stoisko | wszystkie stoiska |
| Stoiska, konta i rangi, słownik wydziałów, liczby studentów, partnerzy, ustawienia | nie | tak |
| Trafienia 10/10, podsumowania, eksport CSV, grafiki | nie | tak |
| Statystyki (`/statystyki`) i Bitwa Wydziałów (`/bitwa`) | publiczne | publiczne |

Konta zakłada admin w panelu. Awaryjne konto: login `admin` + hasło `ADMIN_SECRET` (bez wiersza w bazie, login zastrzeżony;
zmiana `ADMIN_SECRET` wylogowuje). Reset hasła lub usunięcie konta wylogowuje użytkownika. Po 10 błędnych logowaniach w 10 minut
logowanie na dany login jest blokowane na 5 minut (licznik per login, nie per IP, eduroam).

## Limit prób

5 prób dziennie na każdym stanowisku, liczone po kluczu urządzenia (działa między przeglądarkami tego samego telefonu).
Limit 5 trzyma klucz rozszerzony (jeden egzemplarz telefonu, także w kilku przeglądarkach). Identyczne modele telefonów dają ten sam
klucz podstawowy, więc `settings.device_tolerance` (1-50, domyślnie 10, ustawiane w panelu admina) to sufit `5 * tolerancja` prób
łącznie na klucz podstawowy i stanowisko; przy 1 to twardy limit 5 na klucz podstawowy. Panel pokazuje dzienne liczby kluczy.
Bonus za wpisanie kodu ze
stoiska zużywa się dopiero po puli stanowiska. Po zmianie dnia klucz znika, więc trzeba ponownie zeskanować kod QR ze stoiska.

## Dodatkowe losy (promocja w mediach)

Gracz pokazuje wolontariuszowi post (udostępniony wynik albo inny materiał z oznaczeniem helpers_wroclaw i dkms_pl).
Wolontariusz ocenia to sam, niczego o poście nie zapisujemy (ani linku, ani konta). W panelu `/login` przycisk „Dodatkowe losy”
(`POST /api/volunteer/generate-code {kind:'promo'}`) tworzy kod w tabeli `promo_codes` (ten sam format i TTL co kody rejestracyjne,
unikalność w obu tabelach). Gracz wpisuje go na `/potwierdz` (`GET /api/donor/check-code` zwraca `kind:'promo'`, formularz ukrywa wydział,
rok i certyfikat), a `POST /api/donor/redeem-promo` zużywa kod i dodaje `config.PROMO_BONUS` = 5 prób. Kod promo nie dotyka
`donors_stats`, Bitwy ani liczników rejestracji; `register` z takim kodem zwraca 404. Listy kodów pokazują `kind:'promo'`, anulowanie działa dla obu typów.

## Bitwa Wydziałów

Ranking wg rejestracji na 1000 studentów. Liczby studentów i źródło danych wpisuje admin (`GET/PUT /api/admin/students`);
początkowy seed to `app/seed_students.json` (używany tylko, gdy w bazie nie ma jeszcze `faculty_students`). Wydziały bez liczby
studentów oraz „Inne” trafiają do listy bez rankingu.

## Pierwsze wdrożenie

1. `cp .env.example .env`, uzupełnij `ADMIN_SECRET` (długi, losowy), `TURNSTILE_*` (patrz niżej).
   Uzupełnij `LEGAL_OWNER` i `LEGAL_CONTACT` (strony prawne). Opcjonalnie `BOOTSTRAP_BOOTHS=c13:Budynek C-13,w4:Budynek W-4` (`id:Nazwa`; stary format `id:Nazwa:PIN` też działa,
   PIN jest ignorowany) utworzy przy starcie brakujące stoiska; potem usuń tę linię.
2. `docker compose up -d --build` — aplikacja nasłuchuje na `127.0.0.1:8010`, dane w `./data`.
3. Cloudflare, tunel:
   Zero Trust → Networks → Tunnels → istniejący tunel → Public Hostname → dodaj `helpers-pwr.rupary.pl`
   → usługa `http://localhost:8010`.
4. Cloudflare, captcha: Turnstile → Add widget → domena `helpers-pwr.rupary.pl` → klucze (site key i secret key)
   do `.env` (`TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`), potem `docker compose up -d`.
5. Wejdź na `/login` (login `admin`, hasło `ADMIN_SECRET`), **zweryfikuj słownik wydziałów** (seed w `app/seed_dictionary.json` jest tylko
   punktem wyjścia), dodaj stoiska i konta wolontariuszy, wpisz liczby studentów do Bitwy Wydziałów i link do Facebooka w ustawieniach.

## Uruchomienie lokalne i testy

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ADMIN_SECRET=dev COOKIE_SECURE=0 DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/pytest -q
```

Bez kluczy Turnstile captcha jest wyłączona (w logu pojawia się ostrzeżenie).
