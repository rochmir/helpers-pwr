# System wizualny — wg strony dkms.pl/dzialaj/zostan-dawca (CSS dostarczony przez właściciela, 2026-10-26)

Cel: interfejs ma wyglądać jak strona Fundacji DKMS (Bootstrap 5 + ich warstwa). Odwzorowujemy ich tokeny i komponenty,
font zastępczy Inter (ich „DKMS Custom” jest firmowy — nie kopiujemy).

## Skala
- `html { font-size: 62.5% }` → 1rem = 10px. Body: 1.6rem / line-height 1.5 (2.4rem), kolor #000, tło #fff.
- Nagłówki BOLD (700), nie uppercase:
  - h1: 4.2rem/4.8rem → ≥768px 5.1rem/6rem → ≥1200px 6.6rem/7.8rem
  - h2: 3.6rem/4.2rem → 4.5rem/5.1rem → 5.4rem/6rem
  - h3: 2.7rem/3.6rem weight 500 → ≥768px 3rem/3.9rem
  - h4: 1.8rem/2.7rem weight 500 → ≥768px 2.1rem/3rem weight 400
  - title2 (nagłówki kart): 2.4rem/3.3rem bold; title3: 1.8rem/2.7rem 500 → 2.1rem/3rem
  - small/body2: 1.3rem/1.8rem; label: 1.6rem 500
- Kolor tekstu pomocniczego #666.

## Kolory (CSS vars DKMS)
primary #e2001a, primary-variant/hover #d70c24, primary-dualtone #f9ccd1,
secondary (zielony) #30783e / dualtone #dff5d7, tertiary (granat) #2c5a82 / dualtone #dcecfa,
indication (bursztyn, ostrzeżenia/błędy formularzy) #ffb500 / dualtone #fff9eb,
black #000, black-variant #282832, grey-dark #666, grey-medium #b2b2b2, grey-light #d9d9d9, grey-background #f4f4f9.
Linki: #2c5a82, underline.

## Komponenty
- **Przyciski `.btn`**: wysokość 4.8rem (4.2rem <576px), padding 0 2.2rem, radius 9rem (pigułka), font 1.3rem BOLD,
  UPPERCASE, letter-spacing .06em, ikona + tekst gap 1.2rem, `:active { transform: scale(.95) }`, transition .1s.
  - primary: tło #e2001a, biały tekst, hover #d70c24
  - secondary: tło #30783e, hover tło #dff5d7 tekst #30783e
  - inverted-primary: przezroczysty, ramka .2rem #d70c24, tekst czerwony → hover pełny czerwony
  - plain-primary: białe tło, czerwony tekst (na czerwonych blokach)
  - text-* : bez tła, bez paddingu, tekst kolorowy
  - utility: tło #f4f4f9, czarny tekst, hover czarne tło biały tekst
  - disabled: tło #f4f4f9, tekst #666
- **Pola formularzy**: border .2rem solid #d9d9d9, radius 0 (!), padding 1.7rem 2rem, font 1.6rem, hover border #666,
  focus border #000 (bez cienia). Label nad polem 1.6rem, margin-bottom .6rem. Błąd: border #ffb500 + komunikat 1.3rem z
  ikoną w kolorze #ffb500. Gwiazdka wymaganych pól czerwona.
- **Header**: biały, padding 1.8rem 0 (≥992px 3rem góra / 2.4rem dół). Logo DKMS po lewej (132×40), obok/za nim logo PWr, (≥992px) logo Samorządu Studenckiego i białe logo Helpers' Generation na czerwonym kafelku,
  po prawej przyciski CTA (primary „Zostań Dawcą”-style, mniejsze `btn-sm` 4.2rem). Pod spodem opcjonalnie pasek
  sub-nawigacji na tle #f4f4f9 (linki 1.6rem 500, aktywny: czerwony z dolną kreską .3rem #e2001a).
- **Hero „image-header-card”**: pełnoszerokościowy blok na tle primary-dualtone #f9ccd1, duży h1/h2 w czerwieni
  (#e2001a), lead 1.6rem, przycisk primary. Na desktopie dwie kolumny (treść + grafika/element), na mobile jedna.
- **Eyecatcher fulltone**: blok tło #e2001a, biały tekst, radius 1.2rem, padding 2.4rem (→3.6rem 4.8rem), tytuł 2.7–3.6rem
  bold, przycisk `plain-primary` po prawej (desktop) / pod spodem (mobile).
- **Karty `keyfactcard`**: białe, border .2rem #d9d9d9, padding 2.2–3.4rem; wariant „black-typo” tło #f4f4f9 bez ramki;
  wariant czerwony tło #d70c24 biały tekst. Hover kart klikalnych: ramka znika, cień `0 9px 42px #28283217`.
- **Iconbox**: biały okrąg 5.4–6rem, cień `0 3px 36px #2828321f`, ikona czerwona w środku.
- **Kroki „registration-step”**: numerowane „1. …” label 1.8–2.1rem 500, opis 1.6rem #666.
- **Accordion/FAQ**: sekcja na tle #dcecfa, tytuły #2c5a82, separatory .2rem.
- **Tagi/status**: `.status-tag` mała pigułka 1.3rem 500, radius .3rem, padding .3rem .6rem, warianty dualtone
  (np. aktywny = zielony #dff5d7/#30783e, użyty = szary, wygasły = bursztyn #fff9eb/#ffb500).
- **Footer**: tło #f4f4f9, padding 3.6–6rem, tekst 1.3rem #666, logo, pod spodem biały pasek copyright.
- **Kontener**: max-width 1500px, padding boczny 18px → 36px(576) → 42px(768) → 60px(992) → 90px(1200) → 120px(1500).
- Sekcje oddzielone pionowo 3.6rem → 4.8rem → 6rem.
- Listy z czerwonymi kropkami.
