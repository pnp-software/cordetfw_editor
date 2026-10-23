# Release notes: Django 5.2 LTS migration

Branch `upgrade/django-lts`, prepared 2026-10-23. Replaces the production stack recorded in
`requirements-baseline.txt` (Django 3.2.0, unsupported since April 2024).

## Versions

| Component | Before (production) | After |
| --- | --- | --- |
| Python | 3.12.3 | 3.12.3 (unchanged; mod_wsgi does not need rebuilding) |
| Django | 3.2.0 | **5.2.18 LTS** (security support until April 2028) |
| django-import-export / tablib | 3.3.9 / 3.5.0 | 4.4.3 / 3.10.0 |
| django-axes (+ ipware) | 7.0.2 / 7.0.1 | 8.3.1 / 8.0.0 (`django-axes[ipware]`) |
| django-crispy-forms | 2.0 | 2.7 + crispy-bootstrap4 2026.2 |
| django-admin-honeypot | 1.1.0 (PyPI, unmaintained) | vendored `admin_honeypot/` (same app label, tables, data) |
| mysqlclient | 2.2.7 | 2.3.0 |
| cexprtk | 0.4.2 | 0.4.2 |
| Removed (unused) | pytz, setuptools, django-appconf, tablib xls/ods/yaml/html extras | |

Exact resolved set: `requirements-lock.txt`. Tested database servers: MySQL 8.0.42 and 8.4.13.

## Intended visible changes (approved)

1. **Logout is a button that submits a POST form** (Django 5 removed logout via GET). It looks the same in the
   navbar. `GET /editor/logout/` now returns 405, so bookmarks or scripts that call it must use POST.
2. **The admin (`/pnpAdmin/`) shows real timestamps**, e.g. `15-01-2024 10:30:00`. Before, it showed broken
   strftime output such as `%15-%01-%2024 %10:%Jan:%th`. Editor pages are unchanged: they use explicit date formats.
3. **Delete, remove, refresh and member actions are buttons (POST) with a confirmation dialog** (upstream #86,
   Task 6.3): delete a project, remove a project member, delete a ValSet, refresh a Model item, and add a member
   or change its role (RO/RW). Changing actions no longer work through plain links, so a link can no longer change
   data by being opened or prefetched.
   - Old links or bookmarks to project delete (`/editor/<id>/del_project`) and item refresh
     (`.../refresh_spec_item`) now return 405.
   - Old member / ValSet links (`edit_project?user_id=...`, `?del_user_id=...`, `?del_val_set_id=...`) open the
     project page, change nothing and show the warning "This link no longer changes the project. Use the buttons on
     this page."
   - Deleting a NEW spec item now goes through the confirmation page (before, it was deleted immediately).
   - Deleting a ValSet now asks for confirmation (before, it did not).
   - The project delete text now reads "Are you sure you want to delete this project?".
   - The dialog needs `/static/confirm-delete.js` (run `collectstatic`); if the Bootstrap script from the CDN does
     not load, the browser's own confirm dialog is used instead.

## Other changes you may notice

- **Admin:** the Django 5.2 admin look (dark-mode toggle, accessibility attributes). The access-attempt list
  has a new read-only "status" column (django-axes 8). The `/admin/` decoy follows the same templates.
- **Logout from an outdated tab:** a page rendered before the user logged in again (e.g. in another tab) has an
  outdated CSRF token, and its Logout button shows Django's "CSRF verification failed" page. Reloading the page
  fixes it. Django enforces CSRF on logout itself, so this is not worked around.
- **`manage.py dbshell`** now connects with `--default-character-set=utf8`, the same as the application.
- **Login sessions:** the first login after the upgrade rehashes each password (PBKDF2, 260000 →
  1,000,000 iterations). The user's *other* open sessions are logged out once. No data is affected.
- **CSRF:** Django ≥ 4.0 also checks the `Origin` header. Direct HTTPS through Apache + mod_wsgi works
  unchanged. If TLS is terminated by a separate proxy, set the new optional config key
  `"CSRF_TRUSTED_ORIGINS": ["https://<host>"]` in `/etc/dj_cordetfw_config.json`.
- **Response headers:** new `Cross-Origin-Opener-Policy: same-origin` header; the CSRF cookie value is 32 characters (old
  cookies keep working).
- **Export ZIP filenames:** download names containing double quotes are now escaped (CVE-2022-36359).
- **Logout with an unsafe `?next=`:** redirects to `/editor` (before, it redirected back to the logout URL).

## Unchanged (verified)

- Every project ZIP export and spec-item CSV/LaTeX export is **byte-identical**. Evidence: the golden files, and
  the rehearsal on the **production database dump of 2026-10-21**. In that rehearsal, all 11 projects were exported
  without errors (328 CSV/LaTeX exports, 165 pages): 404 files are byte-identical and 164 pages differ only in the
  logout control. With the old code on the migrated database (rollback), all 568 files are identical.
- All editor pages are identical apart from the logout control (33 golden pages).
- Permissions, releases, history chains, value sets, import rules, find/replace, ext. FW Profile refresh.
- The MySQL connection charset stays `utf8` (Django 5.2 would default to utf8mb4). So, as before, 4-byte
  characters (emoji) cannot be stored. Switching is a separate decision: see "Follow-ups".
- Existing passwords, sessions and password-reset links remain valid.
- Login lockout (django-axes: 3 failures, 3 minutes cool-off, IP from `REMOTE_ADDR`), the honeypot
  records at `/admin/`, and the masked axes log lines.

## Database changes

Only one third-party migration, `axes.0010_accessattemptexpiration`, which adds a new table. No existing
table or column is altered. The old code runs unchanged on the migrated database (rehearsed).

## Test evidence

- Characterization suite written on the old stack first: 1143 tests on SQLite (9 MySQL-only skipped) and 1152
  on MySQL; 97% line coverage; 59 byte-exact golden files. Every intended change is documented in
  the test that pins it ("Changed in Task …").
- Gate per upgrade step (`scripts/migration_gate.sh`): pip check, Django check, migration drift, both backends,
  golden diffs, warnings. No deprecation warnings remain (strict run).
- Migration + rollback rehearsal: `docs/migration/rehearsal/REPORT.md`.

## Known limitations / pending

- **Pending external checks:** Apache/mod_wsgi staging and a browser walkthrough (see `ROLLOUT.md`).
- Production collation (from the dump): `editor_*` tables use `utf8mb4_unicode_ci`, as in the tests. One table,
  `axes_accessfailurelog`, is `latin1` (created that way before the migration; not altered).
- 65 pre-existing issues were found and deliberately **not** fixed (`known-issues/README.md`). Several are
  security-relevant or change data: application creation sets items of all projects to CNF, an IDOR on spec items,
  XSS, and SQL injection in the FW Profile queries.

## Follow-ups (separate changes)

1. Fix the high-priority known issues, starting with `add-app-releases-null-app-items` and `idor-item-project`.
2. Decide on utf8mb4 connections (the production tables are already utf8mb4, so this is possible).
3. Plan MySQL 8.0 → 8.4 LTS (MySQL 8.0 reached end of life in April 2026; the suite passes on 8.4.13).
4. Next Django LTS: 6.2 (April 2027). Re-run this suite as the gate.
