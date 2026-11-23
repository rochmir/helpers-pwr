# Graph Report - helpers-pwr  (2026-11-23)

## Corpus Check
- 75 files · ~63,401 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 15 file(s) not represented in the graph (top: .woff2 7, (none) 4, .css 3)

## Summary
- 1080 nodes · 2764 edges · 43 communities (40 shown, 3 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 19 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41

## God Nodes (most connected - your core abstractions)
1. `$` - 104 edges
2. `new_session()` - 53 edges
3. `connect()` - 50 edges
4. `h()` - 44 edges
5. `api()` - 42 edges
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
- `test_settings_and_facebook_in_config()` --calls--> `init_db()`  [EXTRACTED]
  tests/test_iter4.py → app/db.py
- `test_migration_on_fresh_db_and_seed_never_overwrites_edits()` --calls--> `init_db()`  [EXTRACTED]
  tests/test_iter7.py → app/db.py
- `test_screen_with_good_token_works_without_login()` --calls--> `public_url()`  [EXTRACTED]
  tests/test_lecture.py → app/config.py

## Import Cycles
- 2-file cycle: `app/db.py -> app/legal.py -> app/db.py`

## Communities (43 total, 3 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (52): set_setting(), tx(), upgrade_seed_version(), BoothIn, BoothPatch, _check_range(), _check_role(), check_token() (+44 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (40): is_win(), make_match(), new_genotype(), pick_matches(), random_genotype(), roll(), arm_win(), fake_registrations() (+32 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (46): data_dir(), db_path(), warsaw_date(), _add_column(), _backfill_wins(), booth_by_screen_token(), bootstrap_booths(), category_counts() (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (56): C, canvasBlob(), DATE_LONG, dateLong(), drawFooterBand(), drawFrame(), drawGenotypeRow(), drawGraphic() (+48 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (33): add_points(), always_win(), exhaust(), put_students(), roll(), test_cup_day_filter_uses_warsaw_day(), test_cup_ranking_unranked_and_inne(), test_cup_rounding_qualification_and_threshold() (+25 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (46): showCredentials(), boothText(), getConfig(), storageGet(), storageRemove(), storageSet(), boothId, consentOk() (+38 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (44): allWins, booths, checkLine(), deadlineText(), faculties, fillBoothSelects(), fillDeadline(), genotypeCell() (+36 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (24): today(), is_armed(), test_arm_not_consumed_when_limit_reached(), test_arm_win_wins_even_after_has_won(), test_force_win(), test_reset_my_game(), test_test_tools_off_without_env(), test_volunteer_and_anonymous_forbidden() (+16 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (17): dev_no_cache(), ekran(), favicon(), old_battle(), old_panels(), _page(), handler(), _screen_booth() (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (35): jobs, obraz, testy, name, needs, runs-on, steps, on (+27 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (28): claim(), cup_token(), test_booth_admin_crud(), test_vote_invalid_dictionary(), vote_new(), voter(), test_bonus_accumulates_across_vote_and_post(), test_closed_cup_410_gives_no_bonus() (+20 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (14): always_win(), build_old_db(), cup_token_now(), real_win(), roll(), set_clock(), test_cup_closes_at_deadline_boundary(), test_migration_on_fresh_db_and_seed_never_overwrites_edits() (+6 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (21): enter(), force_matches(), roll(), set_clock(), test_actual_vote_gives_twenty(), test_best_today(), test_best_today_win_is_ten_and_resets_next_day(), test_bonus_is_spent_after_the_daily_pool_then_429() (+13 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (25): $, barState, CATEGORIES, countUp(), formatDateRange(), labelTable(), MONTHS_GEN, parseIsoDate() (+17 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (11): add_partner(), delete_partner(), list_partners(), order_partners(), OrderIn, partner_file(), PartnerIn, partners_dir() (+3 more)

### Community 15 - "Community 15"
Cohesion: 0.23
Nodes (21): applyClosed(), CATS, clearSelection(), ctx, FINAL, hideQr(), initVolunteer(), meUrl() (+13 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (11): contest_deadline(), _db_setting(), _deadline(), env_deadline(), format_pl(), iso(), noon_iso(), now() (+3 more)

### Community 17 - "Community 17"
Cohesion: 0.15
Nodes (13): format_updated(), published(), render(), admin_delete(), admin_get(), admin_list(), admin_version(), document_page() (+5 more)

### Community 18 - "Community 18"
Cohesion: 0.16
Nodes (8): consent_updated_at(), seed(), split_title(), _update_untouched(), test_previous_seed_hashes_are_not_the_current_text(), test_seed_update_leaves_manually_edited_document(), test_seed_update_replaces_untouched_v1_only_once(), test_legal_upgrade_v3()

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (7): screen_token(), test_booth_screen_rotation_invalidates_old_link(), test_lecture_booth_ignores_booth_dates(), test_live_stats_split_categories(), test_old_zajecia_link_redirects_to_ekran(), test_screen_with_bad_token_is_404_and_hides_play_path(), test_screen_with_good_token_works_without_login()

### Community 20 - "Community 20"
Cohesion: 0.16
Nodes (6): resolve_booth(), code_status(), cup_qr(), cup_qr_status(), CupQrIn, me()

### Community 21 - "Community 21"
Cohesion: 0.20
Nodes (7): day_bounds(), cup(), cup_route(), faculty_counts(), _faculty_rows(), live(), _wz()

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (7): claim(), ClaimIn, cup_me(), faculties(), _play_path(), vote(), VoteIn

### Community 23 - "Community 23"
Cohesion: 0.23
Nodes (8): clear_staff_cookie(), _booth_view(), BoothIn, choose_booth(), login(), LoginIn, logout(), me()

### Community 24 - "Community 24"
Cohesion: 0.28
Nodes (15): SHAPE_ICONS, SHAPE_NAMES, sleep(), buildReels(), cell(), confetti(), fadeIn(), fill() (+7 more)

### Community 25 - "Community 25"
Cohesion: 0.12
Nodes (15): container_name, env_file, environment, image, logging, ports, restart, volumes (+7 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (15): build, command, environment, image, ports, volumes, ADMIN_SECRET, COOKIE_SECURE (+7 more)

### Community 27 - "Community 27"
Cohesion: 0.16
Nodes (5): _game_signer(), new_game_token(), optional_game_session(), read_game_token(), require_volunteer()

### Community 28 - "Community 28"
Cohesion: 0.21
Nodes (7): _admin_tag(), check_admin_secret(), current_staff(), hash_tag(), optional_staff(), verify_login(), admin_secret()

### Community 29 - "Community 29"
Cohesion: 0.24
Nodes (6): public_url(), booth_list(), booths_public(), get_config(), healthz(), qr_svg()

### Community 30 - "Community 30"
Cohesion: 0.26
Nodes (8): admin_create(), admin_preview(), admin_update(), _body(), DocumentIn, DocumentPatch, PreviewIn, _title()

### Community 31 - "Community 31"
Cohesion: 0.27
Nodes (13): setMessage(), init(), loadBoothChoices(), lsGet(), lsSet(), maybeRedirect(), msg, nextPath() (+5 more)

### Community 32 - "Community 32"
Cohesion: 0.14
Nodes (11): test_admin_delete_vote(), test_dictionary_put(), test_donors_stats_privacy(), test_vote_flow(), vote(), test_cup_vote_gives_bonus_to_existing_session(), test_dictionary_ends_with_other(), test_new_session_from_vote_has_coarse_created_at() (+3 more)

### Community 33 - "Community 33"
Cohesion: 0.14
Nodes (14): test_cup_qr_closed_outside_booth_dates(), test_volunteer_permissions(), volunteer(), test_delete_volunteer_invalidates_session(), test_reset_password_invalidates_session(), test_volunteer_account_lifecycle(), test_volunteer_cannot_manage_accounts(), test_login_roles_and_me() (+6 more)

### Community 34 - "Community 34"
Cohesion: 0.36
Nodes (10): categorySplit(), facultyLabel(), formatWarsawLong(), pollLive(), updateBars(), fmt(), ranking(), render() (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.18
Nodes (4): legal_contact(), render_markdown(), lifespan(), _asset_version()

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (6): current(), _minute(), seconds_to_change(), _token(), valid(), test_qr_token_validity_window()

### Community 37 - "Community 37"
Cohesion: 0.38
Nodes (4): ensure_game_session(), set_game_cookie(), set_staff_cookie(), cookie_secure()

### Community 39 - "Community 39"
Cohesion: 0.29
Nodes (3): _staff_serializer(), secret_key(), test_old_pin_cookie_session_no_longer_valid()

### Community 40 - "Community 40"
Cohesion: 0.70
Nodes (5): cup_closed(), cup_closed_message(), cup_deadline(), _cup_info(), test_default_deadlines_and_message()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `tx()` connect `Community 0` to `Community 1`, `Community 2`, `Community 14`, `Community 17`, `Community 18`, `Community 20`, `Community 22`, `Community 30`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.060694579681921455 - nodes in this community are weakly interconnected._
- **Why does `$` connect `Community 13` to `Community 34`, `Community 3`, `Community 5`, `Community 6`, `Community 15`, `Community 24`, `Community 31`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05028305028305028 - nodes in this community are weakly interconnected._
- **Why does `new_session()` connect `Community 7` to `Community 32`, `Community 4`, `Community 10`, `Community 11`, `Community 12`, `Community 19`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.06126331811263318 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.06428988895382817 - nodes in this community are weakly interconnected._