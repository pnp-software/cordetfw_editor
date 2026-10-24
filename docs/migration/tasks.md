# Django LTS migration: task tracker

Branch: `upgrade/django-lts` · Plan: Django 3.2 → 4.2 (bridge, not deployed) → 5.2 LTS, Python 3.12 throughout.
Gate after every task: `pip check` · `manage.py check` · full pytest on **SQLite and MySQL 8.0** ·
`-Wa` review · `makemigrations --check` · `git diff --check` · no `.actual` golden diffs.
Tests marked `# EXPECTED-CHANGE` may change only in the task named in their comment, with the
decision recorded here.

## Phase 0: Setup
- [x] **Task 0.1** Branch `upgrade/django-lts`, CLAUDE.md harness rules, gitignore
- [x] **Task 0.2** Production freeze recorded (`requirements-baseline.txt`, `baseline.md`), `.venv-baseline` reproduces it
- [x] **Task 0.3** `CORDETFW_CONFIG_PATH` override in settings.py, views.py, ext_cats.py

## Phase 1: Characterization suite (old stack)
- [x] **Task 1.1** Harness: settings_test, pytest.ini, conftest temp_dir isolation, factories, golden helper
- [x] **Task 1.2** Models, access matrix, releases, query visibility
- [x] **Task 1.3** Forms, conversion/markdown/filters, utilities
- [x] **Task 1.4** Views and golden page snapshots
- [x] **Task 1.5** Project/CSV import-export goldens + round trip, ext cats, auth/axes/honeypot
- [x] **Task 1.6a** Suite also green on MySQL 8.0 (collation/charset differences pinned per backend)
- [x] **Task 1.6b** Independent Opus gap review (19 findings)
- [x] **Task 1.6c** Gaps filled (auth/HTTP/persisted state; export/DB backend/ties; page snapshots)
- [ ] **Task 1.7** Baseline frozen: 1134 SQLite / 1143 MySQL tests, 98% coverage, warnings recorded; commit

## Phase 2: Dependency matrix
- [x] **Task 2.1** `dependency-matrix.md`, honeypot decision (vendor)

## Phase 3: Upgrade gates
- [x] **Task 3.1** Behaviour-neutral escape-sequence fixes (constants proven identical)
- [x] **Task 3.2** Django 3.2.0 → 3.2.25: 1 expected change accepted (CVE-2022-36359 filename quote escaping)
- [x] **Task 3.3** Honeypot vendored unchanged (gate), then patched: url→re_path, ugettext→gettext, Signal providing_args
- [x] **Task 3.3b** `queryset=` keyword for Resource.export (import-export 4 prerequisite)
- [x] **Task 3.4** Django 4.2.30 bridge + django-upgrade 1.33.0 (vendored honeypot only); import-export stays 3.3.9.
  Accepted upstream changes (invisible to normal users, no stored-data change):
  - CSRF Origin checking: 4 matrix cases flipped. **Deployment action:** set `CSRF_TRUSTED_ORIGINS`
    (or `SECURE_PROXY_SSL_HEADER`) for the Apache TLS proxy, see Task 4.4.
  - `Cross-Origin-Opener-Policy: same-origin` on every response; CSRF cookie holds 32 chars (old 64-char cookies still accepted).
  - Password rehash 260000 → 600000 PBKDF2 iterations on login/check. Verified that Django 3.2 accepts the new hashes (rollback-safe).
  - Logout with an unsafe `?next=` now redirects to `/editor` (upstream fix of the self-redirect loop).
  - Honeypot decoy follows the Django 4.2 admin login template (matches the real `/pnpAdmin/`).
  - Hidden `s_data` input of a re-rendered invalid form: `value="null"` instead of empty; proven to store identical data.
- [x] **Task 3.4b** import-export 3.3.9 → 4.4.3 + tablib 3.5.0 → 3.10.0 on Django 4.2: all export files byte-identical;
  only the intermediate Dataset holds some ints as strings (tests compare cell text; verified against 3.3.9 output)
- [x] **Task 3.5** Django 4.2.30 → **5.2.18 LTS**. Code changes:
  - `USE_L10N` removed; `DATETIME_FORMAT = 'd-m-Y H:i:s'` + `cordetfw_editor/formats/en/formats.py`
    (**operator-approved visible change**: admin shows `15-01-2024 10:30:00` instead of `%15-%01-%2024 %10:%Jan:%th`;
    app pages, `|date`, numbers unchanged).
  - Logout is a POST form with CSRF token in `base_generic.html` (**operator-approved visible change**); GET → 405.
  - `apply_mysql_connection_defaults()` keeps the MySQL connection charset `utf8` (Django 5.2 would switch to utf8mb4,
    allowing emoji that a rollback would mangle). Switching to utf8mb4 is a separate later decision (needs the
    production table charset, still pending).
  - Test-only: public `Signal.has_listeners()` instead of the private `_live_receivers()`.
  Accepted upstream changes: PBKDF2 1,000,000 iterations (Django 3.2 verifies them: rollback-safe),
  aria attributes on password-reset-confirm inputs and admin row checkboxes, Django 5.2 admin/decoy template.
  All 24 logged-in page goldens differ only in the logout block (checked mechanically).
- [x] **Task 3.6** crispy 2.0 → 2.7 + crispy-bootstrap4 2026.2 (`crispy_bootstrap4` app, `CRISPY_ALLOWED_TEMPLATE_PACKS`); no rendering in app templates, suite unchanged
- [x] **Task 3.7** django-axes 7.0.2 → 8.3.1 (`[ipware]` extra keeps django-ipware 8.0.0: axes uses it when installed, as in
  production), python-ipware 4.1.1. Lockout, cooloff, XFF handling and log masking unchanged.
  Accepted: new read-only 'status' column in the `/pnpAdmin/` access-attempt list.
  **Schema:** adds third-party migration `axes.0010_accessattemptexpiration` (new table; old code ignores it) →
  rehearse in Task 4.2.
- [x] **Task 3.8** import-export / tablib (done as Task 3.4b)
- [x] **Task 3.9** mysqlclient 2.2.7 → 2.3.0 (source build OK), cexprtk 0.4.2 (latest). Removed unused direct pins:
  pytz, setuptools, django-appconf, tablib format extras (MarkupPy, odfpy, openpyxl, et_xmlfile, xlrd, xlwt, PyYAML,
  defusedxml; only CSV is used), asgiref/sqlparse/diff-match-patch now transitive. Test tools pytest 9.1.1,
  pytest-django 4.14.0, pytest-cov 7.1.0 (`requirements-test-baseline.txt` keeps the old pins for `.venv-baseline`).
- [x] **Task 3.10** Exact direct pins + `requirements-lock.txt`; fresh venv from the files reproduces the environment exactly;
  gate green (1141 SQLite / 1150 MySQL), strict DeprecationWarning run green, coverage 97%.

## Phase 4: Real-environment validation (external gates)
- [x] **Task 4.1** Full suite on MySQL 8.0.42 (every gate) and **MySQL 8.4.13 LTS: 1150 passed**. Note: the MySQL 8.0
  series reached end of life in April 2026; production (8.0.46) should plan a move to 8.4 LTS (separate change).
- [x] **Task 4.2a** Local rehearsal on MySQL 8.0 from the 2022 tryout dump + realistic data (`docs/migration/rehearsal/`):
  editor_* rows/checksums unchanged by migrate; 41/41 exports byte-identical old vs new; HTML differs only in the
  logout control; old sessions and passwords work; rollback (old code on migrated DB, no restore) 55/55 identical.
  Note: a user's other sessions are logged out once when their password hash is upgraded at first login.
- [x] **Task 4.2b** Rehearsal on the production dump of 2026-10-21: 11 projects / 328 exports / 165 pages, old vs new
  404 identical + 164 logout-only, rollback 568 identical. Repeat with a fresh dump before cutover.
- [x] **Task 4.3** tryout: `python:3.12-bookworm` + lock file, `mysql:8.4` pinned, healthcheck/`service_healthy` instead of
  `sleep 5`, removed `--default-authentication-plugin` (MySQL 8.4 refuses it), new data dir `mysql84_db_persist/`.
  Verified: isolated `up --build` migrates the 2022 dump schema and serves `/editor/` (HTTP 200).
- [ ] **Task 4.4** (external, operator) Apache/mod_wsgi staging, `check --deploy`, browser walkthrough: `ROLLOUT.md` §1

## Phase 5: Handoff
- [x] **Task 5.1** Independent Opus review of the full diff (no correctness bugs; 9 deployment/UX findings addressed or
  documented), release notes, rollout/rollback procedure, README

## Phase 6: Security fixes for the migration release (track S, plan: docs/fixes/register.md)
- [x] **Task 6.0** Gate green on `8c05151`, local tag `migration-rc1`; draft fix register (62 known ids)
- [x] **Task 6.1** Additional security audit: 3 Opus auditors (authz, injection/output, files/config), 23 findings,
  all reproduced by an independent Opus verifier (38 tests); 10 narrowed, 5 operator checks
- [x] **Task 6.2** Pin audit findings as `KNOWN-ISSUE` tests, `known-issues/security-audit.md`, `known_issue_check.py` in the gate (1179 SQLite / 1188 MySQL)
- [x] **Task 6.3** `1b2bb5a` merge of upstream #86 (deletes via POST; its project scoping of `del_user_id`/`del_val_set_id`
  kept, fixing `edit-project-del-user-unscoped`) + `b22d64e` refresh, del_project, member add/role via POST, role must be
  RO/RW. GET: 405 (del_project, refresh) or confirmation page / ignored parameters. 32 goldens promoted, mechanically
  proven to differ only in the converted controls + delete modal. Gate 1254 SQLite / 1263 MySQL. Opus review: no blocking findings; low-severity follow-ups in Task 6.3b
- [x] **Task 6.3b** `0eb5a54` Review follow-ups: confirm fallback without Bootstrap/requestSubmit, stronger GET sweep test, button group/alignment, warning for old GET member links, release notes + ROLLOUT walkthrough. Gate 1257 SQLite / 1266 MySQL
- [x] **Task 6.4** `56ac216` Cross-project scoping of every id (item, application, ValSet, parent, release, ProjectUser); find/replace needs write access
- [x] **Task 6.4b** `e7af220` Review follow-ups: Default ValSet check via DB collation (MySQL `Défault`), keep `access-first-row` (K) untouched, stronger tests. Gate 1313 SQLite / 1322 MySQL
- [x] **Task 6.5** `ce003fd` `add-app-releases-null-app-items`: no item loop for an unsaved application; Release/Application rows as before.
  Production impact (dump 2026-10-21): 80 project-level items in 4 projects probably confirmed by the bug (74 were NEW,
  6 MOD); operator decision: report only, `docs/fixes/add-app-release-data-impact.md`
- [x] **Task 6.6** `0a7523c` XSS escaping (HTML path): text nodes escape `&<>` only, attributes full `escape()`, `image` (SVG)
  exempt; escape before #iref substitution and markdown. Byte proof: identical output for text without `&<>"'`.
  Gate 1360 SQLite / 1369 MySQL. Found: RW users can store arbitrary markup in `image` fields (forged edit POST, CSV import)
- [x] **Task 6.6b** `69c111d` `image` fields: edit/copy/split ignore a posted value for FW-Profile attributes (like add); every write path
  (forms, CSV import, ZIP import, refresh) rejects dangerous SVG content; checked to reject none of the 240 production diagrams.
  Plus follow-ups from the 6.6 review: `link-suggest-js-string` was stored XSS (HIGH, misjudged by the audit), fixed with a
  JS-string filter that leaves ordinary titles byte-identical. Find & Replace refuses all FW-Profile attributes. Production
  check: 0 of 240 diagrams rejected. Gate 1419 SQLite / 1428 MySQL. Opus review: stopped before payload testing; its
  design finding (a deny-list is fragile for a field rendered raw) leads to Task 6.6c
- [x] **Task 6.6c** `ee966b1` SVG allowlist validator (strict XML, element/attribute allowlist from the production diagrams, validate
  only, never rewrite) on every write path + placeholder on render for stored values that fail; replaces the deny-list. Elements: 7 observed + inert shapes;
  CSS keywords only as observed (position relative, overflow hidden, display none, white-space pre, cursor default/move/
  nw-resize). Production: 240/240 accepted. Gate 1534 SQLite / 1543 MySQL. Test fixtures `<svg/>` -> namespaced documents
- [x] **Task 6.6d** `6d86301` Review fixes for the validator: ReDoS-free number/transform patterns + per-attribute length caps,
  validate only in add mode (invalid stored diagrams can be deleted/edited), no `linebreaksbr` on SVG cells (0 of 240
  production diagrams contain newlines: no byte change), prefixed elements and extra namespace declarations rejected,
  XML-only whitespace, category escaped in link_suggest. Allowlist spec: `docs/fixes/svg-allowlist.md`. Production:
  240/240 accepted. Gate 1884 SQLite / 1893 MySQL
- [x] **Task 6.7** `509d5d8` Optional `AXES_LOCKOUT_PARAMETERS` config key (default unchanged; recommended
  `["ip_address", "username"]`, trade-off: a known username can be locked out for the cool-off); pip-audit 2.10.1:
  no known vulnerabilities (2026-10-23). Gate 1437 SQLite / 1446 MySQL; ROLLOUT §0: pip-audit before cutover.
  Operator answers 2026-10-23: TLS ends at Apache, no proxy (#17 not applicable); HSTS + port 80 redirect by Apache (#23);
  production SECURE_KEY differs from the tracked one (#19 -> K cleanup)
- [x] **Task 6.8** Release gate for track S (HEAD a304e60; full gate 1884 SQLite / 1893 MySQL 8.0):
  - 6.8a `2094c31` rehearsal on the production dump with `docs/fixes/expected-diffs.json`: 404/404 exports byte-identical
    old vs new; 164/164 pages differ only by allowed ids (logout-post 164, post-only-mutations 164, escape-stored-text 17);
    0 unexplained; rollback 568/568 identical; sessions/passwords both directions OK
  - 6.8b MySQL 8.4.13: 1893 passed
  - 6.8c final Opus review of migration-rc1..db56be0: ready with doc fixes (done in 6.8d `aa26a70`)
  - 6.8e/f `a041859`, `a304e60` re-import of production exports (ZIP + 107 CSVs) with OLD and NEW code: identical results,
    0 regressions; pre-existing: 35 items of one project not importable (owner not a member), 448 CSV rows rejected by
    row checks (447 empty required field, 1 identifier) -> track K
  - Remaining: Task 4.4 staging walkthrough (operator, ROLLOUT.md §1)

## Phase 7: Known-issue fixes (track K, branch `fix/known-issues`, plan: docs/fixes/register.md)
Branched from `upgrade/django-lts` at c602bbb (local tag `track-s-rc1`) on 2026-10-24, before the track S deploy
(operator: "we have not yet deployed, but continue with the new branch and the fixes"). Baseline for "unchanged" =
`track-s-rc1`. If staging (Task 4.4) needs a fix on `upgrade/django-lts`, it is merged into this branch.
- [x] **Task 7.0** `5e5ad1d` + 7.1b: compat corpus `tests/golden/compat/` (17 inputs: 9 project ZIPs, 8 spec-item CSVs;
  DB fingerprints recorded on `track-s-rc1` code; tests/test_compat_corpus.py). Fixes declare allowed fingerprint fields
  in docs/fixes/expected-diffs.json `"compat"`; a changed fingerprint always leaves `.actual`, so it must be reviewed and
  promoted. 7.1b: `#iref:<id>` in text normalised to the item rank (ids differ on MySQL), bare `*` patterns rejected
- [x] **Task 7.1** Merge upstream branches: `origin/99` (split deletion), `origin/91` (FW Profile models shared by other
  authors); `origin/100` has 0 commits (nothing to merge).
  `origin/99`: merge a176737 + test eb01138 (gate: SQLite 1885 passed / 9 skipped, MySQL 1894 passed). Users can now
  delete a split item alias (its link points to the original item, outside the normal choices) instead of a form error.
  `origin/91`: merge 8ac1c5c (gate: SQLite 1900 passed / 10 skipped, MySQL 1910 passed). FW Profile models shared
  with the user (shares ro/rw) can be listed, added and refreshed; unavailable models give a clear message; model queries
  are parameterized and close the connection. Register: `ext-cats-sql-injection`, `-connection-leak`,
  `-get-choice-not-found` stay OPEN (FCP paths unfixed).
  7.1b Opus review of 2968724..5e5ad1d: nothing blocking. Visible change to confirm with the operator: refresh is now
  limited to models the user owns or that are shared with them (ro/rw) by e-mail; before, any writer could refresh any
  Model item, so co-authors now need an FW Profile share (also applies to FCP items, which go through the same refresh
  check, while FCP listing/import is still owner-only). New row `refresh-not-shared-double-message`.
- [x] **Task 7.2** Less urgent security (K1), three parallel parts + one Opus review each:
  - 7.2a (11 ids, commits `1f6a350`..`795331d` as cherry-picked): import-no-login-required, login-url-default
    (`/editor/login/`), honeypot-logger-not-connected, access-first-row (any RW row), appform-cats-substring,
    index-username-substring, index-lists-all-projects (non-staff: own/member projects; anonymous: none),
    login-echoes-password, order-by-unrestricted (UI fields, `-field` kept), import-traceback-in-message,
    find-replace-on-release-view. Goldens promoted: login_failed_post.html (password value removed),
    list_data_items_release.html (Find & Replace modal removed on release views). Review follow-ups `a24fd91`.
  - 7.2b: iref-cross-project-disclosure (`#iref` resolved only inside the item's project; foreign ids written by
    form/CSV/ZIP/Find & Replace become `#iref:0`), eval-ref-dos (loop/assignment keywords refused, expansion capped:
    depth 10, 2000 substitutions, 100,000 chars; iterative expansion). Review blocker fixed in 7.2d: keyword ban was
    bypassable with a digit prefix (`2while`). Production check (dump 2026-10-21, aggregates): all 3,875 DataItem/
    EnumValue values evaluate identically with old and new code; max expanded length 121.
  - 7.2c: ext-cats FCP SQL parameterized + connections closed, FCP/model error paths, temp dirs (mkdtemp 0700,
    removed after the response), ZIP import limits + selective extraction, per-row cat/status validation,
    placeholder dev key refused when DEBUG is off. Production: all 16,306 items have a configured cat and a known
    status. Open from the review (-> Task 7.4): a rejected row that another row links to still ends in the
    `import-project-dangling-link-crash` KeyError.
- [x] **Task 7.3** Crashes -> proper responses (K2): 11 ids, one commit each (`0817cb6`..`d8ce28e`):
  change-password-no-response, conv-date-nameerror, disp-trac-plink-none, enum-value-no-type, dataitem-no-plink,
  redirect-int-parent, add-p-parent-label-keyerror (subtitle now uses the p_link label, e.g. "Packet ..."),
  outcomponent-disp-short-keyerror (configs.json: `value` removed from OutComponent disp_short; that view always
  crashed), add-spec-item-val-set-post, import-spec-items-undefined-i, list-500s (unknown cat 404, bad disp -> disp_def,
  page via get_page, invalid expand params ignored). Gate 1980 SQLite / 1990 MySQL. Opus review: nothing blocking;
  follow-ups 7.3b (Unicode-digit expand_id, `i` defined before the import loop, register test columns)
- [ ] **Task 7.4** Import fidelity and atomicity (K3)
  - 7.4b spec-item CSV import (`8f521d4`..`1af4aa9`): exp-ref-no-dots (link references with dots/dashes resolve),
    import-spec-items-no-rollback + -abort-no-summary (per-row atomic import, one summary "N imported, M rejected"
    with line numbers and reasons, warnings), csv-export-not-reimportable (empty required text/choice fields
    imported with a warning), import-link-ambiguous (unknown/ambiguous links reported). Opus review: nothing
    blocking; follow-ups 7.4c: empty or non-numeric integer cells rejected with a clear reason (they cannot be
    stored empty), echoed link text truncated to 80 chars. Production (aggregates): 0 live items link to a target
    whose domain/name contains characters outside [A-Za-z0-9_], so the wider link pattern changes no import result
    of production exports
  - 7.4a project ZIP import (`fa60e58`..`7dddd28`): one transaction (nothing created on failure), dangling or
    rejected link targets cleared and reported, owner-not-member per operator rule (existing account -> RO member,
    else project owner), role / application_version / created_at / updated_at / CRLF / empty application cats /
    s_data restored, member names `./x.csv` accepted. Compat corpus: every ZIP input now reproduces the exported
    values; re-export of an imported project equals the source export. Gate 2108 SQLite / 2118 MySQL
- [ ] **Task 7.5** Export correctness, each byte change approved (K4)
- [x] **Task 7.6** UI/behaviour bugs (K5): 8 ids (`fba05cb`.. as cherry-picked, ending `ccefe19`): help-double-space,
  owner-empty-names, form-none-literal, p-link-selection-lost, copy-unreachable-valset-message,
  refresh-not-shared-double-message, refresh-timestamp-overwritten, ref-link-backslash (browsers already treated `\`
  as `/`). Goldens promoted one by one (help text, `value="None"` -> empty, p_link/owner `selected`, `\list_spec_items`
  -> `/list_spec_items`). `s-data-string` not fixed: changes stored data/export -> ticket docs/fixes/tickets/s-data-string.md.
  Opus review of 7.6 + 7.7: refresh-timestamp-overwritten fix reverted (`af4c9af`, WONTFIX: release views filter CNF
  items by `updated_at`; an older external timestamp listed an item twice in an old release); migrations 0012/0013
  verified no-op on MySQL and old code runs on the migrated DB. New row `refresh-cnf-obs-copy-new-content`.
  7.6b `e2789e3` + `aa36b90`: form-choice-empty-silent-default (blank option in edit/copy/split when a required
  choice is stored empty or invalid; add mode unchanged)
- [x] **Task 7.7** Model defaults (K6): naive-created-at-default (migration 0012, aware UTC default) and
  release-version-default-str (migration 0013, int defaults). sqlmigrate: MySQL no-op for both; SQLite rebuilds the
  table with rows copied unchanged. No data migration; rollback with the old code works (no MySQL DDL)
- [ ] **Task 7.8** Decide-only items (K7)
- [ ] **Task 7.9** Release gate for track K

## Decisions
- 2026-10-23 (operator): commit one checkpoint per gate on `upgrade/django-lts`, never pushed.
  Stop and ask on EXPECTED-CHANGE decisions or on gates that cannot pass without a behaviour change.
- 2026-10-23 (operator): Task 3.5 converts `DATETIME_FORMAT` to Django format syntax
  (`d-m-Y H:i:s`), so the admin shows real dates instead of the broken strftime output. App
  pages must stay byte-identical. Together with POST logout, this is an intended visible change.
- 2026-10-23 (operator): accepted the CVE-2022-36359 change from Task 3.2. Upstream security/protocol
  changes that are invisible to users and don't touch stored data may be accepted without asking,
  and are listed in the gate commit and here. User-visible or data-affecting changes need approval.
- 2026-10-23 (operator): after the extra security audit, these fixes ship WITH the migration (track S, Phase 6):
  cross-project scoping, add-app-releases-null-app-items, GET->POST for state changes (upstream branch 86 merged
  and extended; delete/remove links become buttons, old bookmarks to those actions get 405), XSS escaping after
  the production-dump scan, and optional deployment config keys + ROLLOUT checks. Everything else, including
  iref-cross-project-disclosure and eval-ref-dos, goes to `fix/known-issues` (track K). No schema migration in
  track S; exports stay byte-identical.
- 2026-10-23 (operator), Task 6.6, after a local scan of the production dump of 2026-10-21 (aggregates only:
  16,306 items, 9 projects; stored markup = 240 inline SVG diagrams in Model/FCP `value` from FW Profile, outside
  SVG one stray `<any>` and one `<code>`; no script, `javascript:` or event handlers): `image` fields stay unescaped
  in track S (SVG allowlist sanitiser -> K, `image-svg-unsanitised`); `<code>` is shown as literal text; text nodes
  escape only `&`, `<`, `>` and attributes get full `escape()`. Expected: about 170 live items change page bytes;
  visible only for the `<any>`/`<code>` rows and 4 tooltips no longer truncated at a `"`.
- 2026-10-23: the scan also showed 0 cross-project `#iref` (11 dangling), no loop/assignment keywords in eval_ref
  values (`[` 139 rows, `;` 8: must stay allowed), max #iref depth 4. Input for K fixes of `iref-cross-project-disclosure`
  and `eval-ref-dos`.
- 2026-10-23 (operator), Task 6.6b: `image` (SVG) fields can be written with arbitrary markup by RW users (forged edit POST,
  CSV import), and they render raw. Close the form path (ignore posted FW-Profile attributes in edit/copy/split, as add
  does) and reject dangerous content on every write path (script, event-handler attributes, javascript:, foreignObject,
  iframe/embed/object, href, plus other active SVG elements, provided no production diagram is rejected). Full allowlist
  sanitiser stays in track K (`image-svg-unsanitised`).
- 2026-10-23 (operator), Task 6.6c: replace the SVG deny-list by an allowlist validator in track S (validate, never rewrite;
  must accept all 240 production diagrams; operator approves the allowlist).
- 2026-10-24 (operator), track K: `access-first-row` -> write access if ANY of the user's ProjectUser rows for the
  project is RW. Spec-item CSV import (`import-spec-items-no-rollback`, `-abort-no-summary`) -> keep per-row import
  (valid rows saved, invalid skipped) and always end with a summary (N imported, M rejected with line + reason).
  `index-lists-all-projects` -> non-staff users see only projects they own or are members of; staff see all.
  Export byte changes: undecided; one ticket per change in docs/fixes/tickets/ (for GitHub and for checking the
  scripts that read the exports). None of them is implemented before approval.
- 2026-10-24, aggregate scan of the production dump of 2026-10-21 for Task 7.2: all 34 applications have categories that
  are exact members of their project's categories (`appform-cats-substring` can be tightened without data impact);
  no user has two ProjectUser rows for one project (`access-first-row` changes nothing for real data); 19 active users
  (2 staff), 1 active non-staff user is in no project and will see an empty index after `index-lists-all-projects`.
- 2026-10-24 (operator): project ZIP import, item owner neither owner nor member: if the account exists on the target
  server keep the owner and add them as RO member of the imported project, otherwise reassign the item to the project
  owner; both listed in the import message. Spec-item CSV import: accept empty required fields and list those rows as
  warnings (cause: docs/fixes/csv-empty-required-fields.md). `form-choice-empty-silent-default`: blank option shown
  when the stored value is empty; saving then requires a conscious choice.
