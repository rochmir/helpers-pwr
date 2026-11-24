# Graph Report - helpers-pwr  (2026-11-24)

## Corpus Check
- 53 files · ~63,860 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 15 file(s) not represented in the graph (top: .woff2 7, (none) 4, .css 3)

## Summary
- 1132 nodes · 2819 edges · 44 communities (40 shown, 4 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 19 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a66af113`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- admin.py
- routes/game.py
- db.py
- cert.js
- test_iter4.py
- graj.js
- admin.js
- test_api.py
- main.py
- with
- test_v3.py
- test_iter7.py
- new_session
- $
- partners.py
- wolontariusz.js
- config.py
- routes/legal.py
- connect
- test_lecture.py
- app/__init__.py
- stats.py
- cup.py
- auth.py
- reels.js
- app
- environment
- app/game.py
- potwierdz.js
- misc.py
- Connection
- api
- helpersi-pwr
- Polityka prywatności
- Regulamin Międzywydziałowego Turnieju „Puchar Dawcy PWr”
- Regulamin symulatora edukacyjnego i konkursu twórczego „HLA Match Maker”
- now
- test_admin_test.py
- upgrade_seed_version
- iso
- cup_deadline
- lokalnie.sh script
- get_db

## God Nodes (most connected - your core abstractions)
1. `$` - 104 edges
2. `new_session()` - 53 edges
3. `connect()` - 51 edges
4. `h()` - 44 edges
5. `api()` - 43 edges
6. `tx()` - 34 edges
7. `volunteer()` - 31 edges
8. `claim()` - 28 edges
9. `vote()` - 26 edges
10. `init_db()` - 25 edges

## Surprising Connections (you probably didn't know these)
- `test_force_win()` --calls--> `connect()`  [EXTRACTED]
  tests/test_admin_test.py → app/db.py
- `test_password_hash_not_plaintext()` --calls--> `connect()`  [EXTRACTED]
  tests/test_iter3.py → app/db.py
- `test_migration_on_fresh_db_and_seed_never_overwrites_edits()` --calls--> `init_db()`  [EXTRACTED]
  tests/test_iter7.py → app/db.py
- `test_cup_closes_at_deadline_boundary()` --calls--> `cup_deadline()`  [EXTRACTED]
  tests/test_iter7.py → app/config.py
- `test_default_deadlines_and_message()` --calls--> `contest_deadline()`  [EXTRACTED]
  tests/test_iter7.py → app/config.py

## Import Cycles
- 2-file cycle: `app/db.py -> app/legal.py -> app/db.py`

## Communities (44 total, 4 thin omitted)

### Community 0 - "admin.py"
Cohesion: 0.06
Nodes (51): get_dictionary(), tx(), BoothIn, BoothPatch, _check_range(), _check_role(), check_token(), create_booth() (+43 more)

### Community 1 - "routes/game.py"
Cohesion: 0.06
Nodes (33): now_iso(), today(), arm_win(), fake_registrations(), FakeIn, force_win(), ForceWinIn, reset_my_game() (+25 more)

### Community 2 - "db.py"
Cohesion: 0.15
Nodes (11): _add_column(), _drop_column(), get_booth_hours(), get_students(), _migrate(), _migrate_cup_contest(), _migrate_v3(), _migrate_v3b() (+3 more)

### Community 3 - "cert.js"
Cohesion: 0.09
Nodes (32): C, canvasBlob(), DATE_LONG, drawFooterBand(), drawFrame(), drawGenotypeRow(), drawHeader(), drawLogo() (+24 more)

### Community 4 - "test_iter4.py"
Cohesion: 0.08
Nodes (31): add_points(), always_win(), exhaust(), put_students(), roll(), test_cup_day_filter_uses_warsaw_day(), test_cup_ranking_unranked_and_inne(), test_cup_rounding_qualification_and_threshold() (+23 more)

### Community 5 - "graj.js"
Cohesion: 0.09
Nodes (47): dateLong(), drawGraphic(), makeCanvas(), prepare(), renderDonorCert(), renderPlayerCert(), renderResultCert(), renderSocial() (+39 more)

### Community 6 - "admin.js"
Cohesion: 0.11
Nodes (43): allWins, booths, checkLine(), deadlineText(), faculties, fillBoothSelects(), fillDeadline(), genotypeCell() (+35 more)

### Community 7 - "test_api.py"
Cohesion: 0.07
Nodes (20): test_reset_my_game(), seed_regs(), test_admin_delete_vote(), test_admin_summary_day_vs_all(), test_booth_admin_crud(), test_csv_export(), test_csv_export_zestawienie(), test_dictionary_put() (+12 more)

### Community 8 - "main.py"
Cohesion: 0.05
Nodes (19): dev_no_cache(), booth_by_screen_token(), ekran(), favicon(), old_battle(), old_panels(), _page(), handler() (+11 more)

### Community 9 - "with"
Cohesion: 0.06
Nodes (35): jobs, obraz, testy, name, needs, runs-on, steps, on (+27 more)

### Community 10 - "test_v3.py"
Cohesion: 0.09
Nodes (39): test_volunteer_and_anonymous_forbidden(), claim(), cup_token(), test_cup_qr_closed_outside_booth_dates(), test_volunteer_permissions(), test_vote_invalid_dictionary(), volunteer(), voter() (+31 more)

### Community 11 - "test_iter7.py"
Cohesion: 0.07
Nodes (17): always_win(), build_old_db(), cup_token_now(), real_win(), roll(), set_clock(), test_bonus_mechanics_present(), test_cup_closes_at_deadline_boundary() (+9 more)

### Community 12 - "new_session"
Cohesion: 0.10
Nodes (25): current(), test_arm_not_consumed_when_limit_reached(), enter(), new_session(), test_admin_summary_game_by_day(), test_forced_win(), test_roll_limit_then_daily_reset(), test_roll_requires_session_and_booth() (+17 more)

### Community 13 - "$"
Cohesion: 0.16
Nodes (26): loadDictionary(), loadStudents(), $, barState, CATEGORIES, categorySplit(), countUp(), facultyLabel() (+18 more)

### Community 14 - "partners.py"
Cohesion: 0.13
Nodes (11): add_partner(), delete_partner(), list_partners(), order_partners(), OrderIn, partner_file(), PartnerIn, partners_dir() (+3 more)

### Community 15 - "wolontariusz.js"
Cohesion: 0.23
Nodes (21): applyClosed(), CATS, clearSelection(), ctx, FINAL, hideQr(), initVolunteer(), meUrl() (+13 more)

### Community 16 - "config.py"
Cohesion: 0.16
Nodes (8): contest_deadline(), data_dir(), _db_setting(), _deadline(), env_deadline(), format_pl(), parse_deadline(), secret_key()

### Community 17 - "routes/legal.py"
Cohesion: 0.06
Nodes (33): legal_contact(), consent_updated_at(), format_updated(), published(), render_markdown(), seed(), split_title(), _update_untouched() (+25 more)

### Community 18 - "connect"
Cohesion: 0.19
Nodes (20): db_path(), warsaw_date(), bootstrap_booths(), connect(), get_setting(), init_db(), test_migration_drops_major(), test_bootstrap_booths() (+12 more)

### Community 19 - "test_lecture.py"
Cohesion: 0.13
Nodes (8): screen_token(), test_booth_screen_rotation_invalidates_old_link(), test_lecture_booth_ignores_booth_dates(), test_lecture_code_is_memorable_on_rotation(), test_lecture_code_opens_screen_without_login(), test_live_stats_split_categories(), test_pass_is_lecture_flag(), test_screen_with_bad_token_is_404_and_hides_play_path()

### Community 20 - "app/__init__.py"
Cohesion: 0.12
Nodes (7): resolve_booth(), category_counts(), code_status(), cup_qr(), cup_qr_status(), CupQrIn, me()

### Community 21 - "stats.py"
Cohesion: 0.18
Nodes (9): day_bounds(), summary(), cup(), cup_route(), faculty_counts(), _faculty_rows(), live(), _wz() (+1 more)

### Community 22 - "cup.py"
Cohesion: 0.19
Nodes (7): claim(), ClaimIn, cup_me(), faculties(), _play_path(), vote(), VoteIn

### Community 23 - "auth.py"
Cohesion: 0.06
Nodes (28): _admin_tag(), check_admin_secret(), clear_staff_cookie(), current_staff(), ensure_game_session(), _game_signer(), hash_tag(), new_game_token() (+20 more)

### Community 24 - "reels.js"
Cohesion: 0.17
Nodes (24): qrUrl(), SHAPE_ICONS, SHAPE_NAMES, sleep(), buildReels(), cell(), confetti(), fadeIn() (+16 more)

### Community 25 - "app"
Cohesion: 0.12
Nodes (15): container_name, env_file, environment, image, logging, ports, restart, volumes (+7 more)

### Community 26 - "environment"
Cohesion: 0.12
Nodes (15): build, command, environment, image, ports, volumes, ADMIN_SECRET, COOKIE_SECURE (+7 more)

### Community 27 - "app/game.py"
Cohesion: 0.17
Nodes (12): is_win(), make_match(), new_genotype(), pick_matches(), random_genotype(), roll(), count_matches(), test_make_match_exact_positions() (+4 more)

### Community 28 - "potwierdz.js"
Cohesion: 0.21
Nodes (17): setMessage(), buildFaculties(), buildYears(), choose(), form, ICONS, init(), LABELS (+9 more)

### Community 29 - "misc.py"
Cohesion: 0.22
Nodes (7): public_url(), booth_list(), booths_public(), get_config(), healthz(), qr_svg(), test_screen_with_good_token_works_without_login()

### Community 30 - "Connection"
Cohesion: 0.18
Nodes (8): _backfill_wins(), create_booth(), ensure_lecture_booth(), fresh_genotype(), genotype_taken(), _insert_win(), new_lecture_screen_code(), record_win()

### Community 31 - "api"
Cohesion: 0.16
Nodes (21): refreshTestStatus(), showPlayLink(), api(), boothText(), fillBoothList(), init(), openEndDialog(), showBoothList() (+13 more)

### Community 32 - "helpersi-pwr"
Cohesion: 0.12
Nodes (15): Aktualizacja, Dokumenty prawne, helpersi-pwr, Jak powstaje obraz, Jednorazowa konfiguracja GHCR, Konkurs i Token Losu, Limit prób, Migracja z obecnego wdrożenia (+7 more)

### Community 33 - "Polityka prywatności"
Cohesion: 0.18
Nodes (10): 1. Informacje ogólne, 2. Administratorzy danych, 3. Jakie dane przetwarza Serwis, 4. Pliki cookies i pamięć przeglądarki, 5. Dostawcy usług i przekazywanie danych, 6. Konkurs „HLA Match Maker” (Facebook), 7. Prawa osób, których dane dotyczą, 8. Zautomatyzowane decyzje (+2 more)

### Community 34 - "Regulamin Międzywydziałowego Turnieju „Puchar Dawcy PWr”"
Cohesion: 0.18
Nodes (10): § 1. Postanowienia ogólne, § 2. Uczestnicy i Wydziały, § 3. Zasady przyznawania punktów, § 4. Wyłonienie zwycięzcy, § 5. Nagrody i ogłoszenie wyników, § 6. Komisja Skrutacyjna, § 7. Protesty, § 8. Dane osobowe i wizerunek (+2 more)

### Community 35 - "Regulamin symulatora edukacyjnego i konkursu twórczego „HLA Match Maker”"
Cohesion: 0.20
Nodes (9): § 1. Postanowienia ogólne, § 2. Cele, § 3. Zasady korzystania z Symulatora, § 4. Konkurs – uczestnicy i zadanie, § 5. Komisja i ocena, § 6. Nagrody i prawa autorskie, § 7. Dane osobowe, § 8. Reklamacje i postanowienia końcowe (+1 more)

### Community 36 - "now"
Cohesion: 0.22
Nodes (11): now(), _minute(), seconds_to_change(), _token(), valid(), set_clock(), test_expired_pass_gives_403_even_when_exhausted(), test_pass_is_per_booth_and_expires() (+3 more)

### Community 37 - "test_admin_test.py"
Cohesion: 0.29
Nodes (3): test_arm_win_wins_even_after_has_won(), test_force_win(), test_test_tools_off_without_env()

### Community 38 - "upgrade_seed_version"
Cohesion: 0.50
Nodes (3): set_setting(), upgrade_seed_version(), test_ensure_lecture_booth_copies_old_settings_token()

### Community 40 - "cup_deadline"
Cohesion: 0.53
Nodes (6): cup_closed(), cup_closed_message(), cup_deadline(), _cup_info(), test_deadline_env_override_and_surfaces(), test_default_deadlines_and_message()

## Knowledge Gaps
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `tx()` connect `admin.py` to `routes/game.py`, `db.py`, `upgrade_seed_version`, `partners.py`, `routes/legal.py`, `connect`, `app/__init__.py`, `cup.py`, `Connection`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Should `admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06260406260406261 - nodes in this community are weakly interconnected._
- **Why does `$` connect `$` to `cert.js`, `graj.js`, `admin.js`, `wolontariusz.js`, `reels.js`, `potwierdz.js`, `api`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Should `routes/game.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06345848757271286 - nodes in this community are weakly interconnected._
- **Why does `connect()` connect `connect` to `routes/game.py`, `db.py`, `test_iter4.py`, `test_admin_test.py`, `upgrade_seed_version`, `test_api.py`, `main.py`, `test_v3.py`, `get_db`, `new_session`, `routes/legal.py`, `test_lecture.py`, `app/__init__.py`, `stats.py`, `Connection`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Should `cert.js` be split into smaller, more focused modules?**
  _Cohesion score 0.09090909090909091 - nodes in this community are weakly interconnected._
- **Should `test_iter4.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07729468599033816 - nodes in this community are weakly interconnected._