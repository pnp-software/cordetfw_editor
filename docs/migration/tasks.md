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
- [ ] **Task 3.4** Django 4.2 bridge (+ django-upgrade); import-export stays 3.3.9 (4.1.1 breaks on Django 3.2)
- [ ] **Task 3.4b** import-export 3.3.9 → 4.x on Django 4.2
- [ ] **Task 3.5** Django 5.2 LTS: USE_L10N removal (decide date rendering: app templates use explicit `|date`, admin
  currently shows broken strftime output), POST logout, MySQL utf8mb4 connection default, CSRF Origin
  checking → `CSRF_TRUSTED_ORIGINS` for the Apache proxy
- [ ] **Task 3.6** crispy + crispy-bootstrap4
- [ ] **Task 3.7** axes / ipware
- [ ] **Task 3.8** import-export / tablib
- [ ] **Task 3.9** mysqlclient, cexprtk, remaining packages, test tools
- [ ] **Task 3.10** Exact pins, `requirements-lock.txt`, fresh-venv reproduction

## Phase 4: Real-environment validation (external gates)
- [ ] **Task 4.1** Full suite on MySQL 8.0.x (matching production) and 8.4
- [ ] **Task 4.2** Sanitized production DB copy: migrate rehearsal, export ZIP old vs new identical
- [ ] **Task 4.3** tryout Docker files → Python 3.12, pinned MySQL, healthcheck
- [ ] **Task 4.4** Apache/mod_wsgi staging, `check --deploy`, browser walkthrough

## Phase 5: Handoff
- [ ] **Task 5.1** Code + security review, release note, rollout/rollback, README

## Decisions
- 2026-10-23 (operator): commit one checkpoint per gate on `upgrade/django-lts`, never pushed.
  Stop and ask on EXPECTED-CHANGE decisions or on gates that cannot pass without a behaviour change.
- 2026-10-23 (operator): Task 3.5 converts `DATETIME_FORMAT` to Django format syntax
  (`d-m-Y H:i:s`), so the admin shows real dates instead of the broken strftime output. App
  pages must stay byte-identical. Together with POST logout, this is an intended visible change.
- 2026-10-23 (operator): accepted the CVE-2022-36359 change from Task 3.2. Upstream security/protocol
  changes that are invisible to users and don't touch stored data may be accepted without asking,
  and are listed in the gate commit and here. User-visible or data-affecting changes need approval.
