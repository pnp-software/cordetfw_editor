# MySQL migration rehearsal: Django 3.2 -> 5.2 (branch upgrade/django-lts)

## Security fixes (Phase 6) run (2026-10-24)

Task 6.8a. OLD = baseline `cd87ccb` (`.venv-baseline`), NEW = branch `upgrade/django-lts` at `db56be0` (`.venv`), ROLLBACK = old
code on the migrated database. Same production dump (2026-10-21) and the same disposable MySQL 8.0 container; the
`.sql.bz2` dump is decompressed into the scratch directory and deleted by the script. Only aggregates are recorded here.
Command: `REHEARSAL_DUMP=<dump>.sql.bz2 python3 docs/migration/rehearsal/rehearse.py --allow docs/fixes/expected-diffs.json`
(runtime about 15 minutes on the production-size data). The script exits non-zero if any page is UNEXPLAINED, any export differs,
or a rollback comparison differs; this run: **PASS (exit 0)**. `worker.py` needed no change (it only GETs pages and exports; the
POST-only mutations are not driven by the snapshot).

Every HTML page is classified identical / differs only by allowed ids / UNEXPLAINED. The allowlist is
`docs/fixes/expected-diffs.json`; each id is a named normaliser in `rehearse.py`, applied to both old and new HTML. Exports
(spec-item CSV and LaTeX, project ZIP members, Content-Disposition headers, ZIP name lists) have no normaliser and must be
byte-identical.

| Check | Result |
| --- | --- |
| Old `migrate`; new `migrate --plan`; editor_* rows and checksums across migrate | no-op; only `axes.0010_accessattemptexpiration`; identical |
| Snapshot coverage (old / new / rollback) | 11 projects, 328 spec-item CSV/LaTeX exports, 164 saved list/index pages (165 requests), 0 failing requests each |
| Exports old vs new | 404 of 404 byte-identical (0 different) |
| HTML old vs new | 164 pages: 0 identical, 164 allowed, **0 UNEXPLAINED** |
| Allowed by id (a page can have several) | `logout-post` 164, `post-only-mutations` 164, `escape-stored-text` 17, `link-suggest-js` 0 (that template is only in the forms, not in the snapshot) |
| Combinations | `logout-post`+`post-only-mutations` 147; those two plus `escape-stored-text` 17 |
| `escape-stored-text` detail | 17 list pages, 151 diff hunks (one changed line each), 35 distinct changed lines; hunks containing `&amp;` 137, `&gt;` 14, `&lt;` 10 (a hunk can contain several) |
| Rollback (old code on migrated DB) vs old | 568 of 568 identical (404 exports + 164 pages), 0 different |
| Data written by new code, read by old code | 404 exports identical; the write changed 7 files vs the earlier new export |
| Sessions / passwords | saved old cookie valid under new code before any password login; 4/4 password logins under new and under rollback (plus the new-stack user under old code); cookie invalidated after the hash upgrade, as documented above; a cookie minted by the new code is accepted by the old code |
| Fingerprints | new vs old: editor rows and checksums identical; new vs rollback: editor rows identical, same migrations |
| Admin (axes / honeypot) | honeypot: 319 attempts listed under old, new and rollback. axes: the one attempt populated under the old stack was visible there (1) but already expired when the new stack was checked (0). `AXES_COOLOFF_TIME` is 3 minutes and about 10 minutes elapse between populate and the new-stack check on production-size data (old snapshot, migrate); this is cool-off expiry, not a migration effect (the earlier runs finished faster). A rollback-side failed login created a normal attempt (1) |

`escape-stored-text` accepts a diff hunk only if `html.unescape` of the old and the new hunk are identical and the new hunk
contains an entity (`&amp; &lt; &gt; &quot; &#x27;`) whose raw character the old hunk contained; anything else leaves the page
UNEXPLAINED. In this run every remaining difference after the other normalisers was of that kind. Note the whitespace
handling in `post-only-mutations`: whitespace-only lines are dropped (outside textarea/pre) and marker lines are stripped, because the old
and new templates leave different template-tag blank lines around the converted controls; the normaliser was checked against
the 32 goldens changed by Task 6.3 (old vs new: 32/32 explained) before use. The snapshot pages are the index and the
list pages; `edit_project` is covered by that golden check only.

## Production data run (2026-10-23)

Run with `REHEARSAL_DUMP=<production dump of 2026-10-21, mysqldump 8.0.46>` on the disposable MySQL 8.0
container. The production data never left the developer machine and is not stored in the repository; only
aggregate results are recorded here. Since this run, the script logs in as each project's owner, so it can
read every project, and it fails if the old and new runs have different failing requests.

| Check | Result |
| --- | --- |
| Old `migrate` on the production schema | no-op (already current) |
| New `migrate --plan` | only `axes.0010_accessattemptexpiration` |
| editor_* rows across new migrate | identical |
| Snapshot coverage (old / new / rollback) | 11 projects, 328 spec-item CSV/LaTeX exports, 165 pages, 0 failing requests each |
| Old vs new | 404 byte-identical files, 164 pages differ only in the logout control, 0 other differences |
| Rollback (old code on migrated DB) vs old | 568 identical, 0 different |
| Data written by new code, read by old code | 404 identical |
| Sessions, passwords, axes/honeypot admin | PASS (as below) |

## Initial run (2022 tryout dump)

Run date 2026-10-23, repo HEAD 3993327 (working tree had uncommitted edits in settings.py and tests/test_auth.py that were not made by this rehearsal). Result: **all checks PASS**, no unexplained differences.

## Re-running
    python3 docs/migration/rehearsal/rehearse.py [--keep] [--allow docs/fixes/expected-diffs.json]     # ~1 minute (2022 dump), needs docker + both venvs
Files: `rehearse.py` (driver, comparisons, cleanup), `worker.py` (runs inside one Django stack: populate, fingerprint, snapshot, checks). Scratch output (logs per step, old/ new/ rollback/ trees, results.json, fingerprints) is under
`/tmp/claude-1000/-home-pstump-Projects-cordetfweditor-migration/2d4443f2-25ba-4bd2-b5c9-d9a3aa33ed64/scratchpad/rehearsal/` (override with REHEARSAL_SCRATCH). The script drops the database and removes the worktree at the end (`--keep` skips this).

## Environment
- MySQL 8.0 (docker `cordetfw-mysql-test`, 127.0.0.1:33306, root), new DB `cordetfw_rehearsal` (utf8mb4 / utf8mb4_unicode_ci), seeded from `tryout/mysql_init/cordetfw.sql` (2022 phpMyAdmin dump, 1 user `admin` with a 216000-iteration hash).
- OLD stack: `git worktree add --detach <scratch>/old-code cd87ccb`, `.venv-baseline/bin/python` (Django 3.2.0, import-export 3.3.9, axes 7.0.2, PyPI admin-honeypot 1.1.0), cwd = the worktree.
- NEW stack: repo tree, `.venv/bin/python` (Django 5.2.18, vendored admin_honeypot).
- Both: `DJANGO_SETTINGS_MODULE=cordetfw_editor.settings`, same config file (`rehearsal_config.json`, same SECURE_KEY, DEBUG false, BASE_URL /editor, temp_dir per call). Both connect with charset utf8 (the new settings keep it explicitly).
- Commands (per stack): `manage.py showmigrations`, `migrate --noinput`, `migrate --plan`, `check`, and `python worker.py <cmd>`; every invocation is logged in `logs/NN_*.log`.

## Data populated with the OLD stack
2 projects (ids 13 and 14, because the 2022 dump left AUTO_INCREMENT counters; "Alpha Proj" with application "App One" + Requirement/ParReq items, 3 ValSets, RO/RW project users; "Größe Beta ☺" without application), 9 releases (project and application releases made by POSTing to the real release views, i.e. do_project_release / do_application_release, 2 project releases of Alpha), 27 spec items in states NEW/MOD/CNF/OBS/DEL with `previous` chains (3 deep), p_link/s_link, `#iref:` references (incl. a dangling one), BMP unicode, s_data JSON (nested), ids 1000/1234/2001, n1=2147483647, n2=-2147483648, 12345, -7, 1000000. 4 users with PBKDF2 (260000) passwords, one real login via POST /editor/login/ (session cookie saved), 1 failed login (axes AccessAttempt) and 1 POST to /admin/login/ (honeypot LoginAttempt).

## Results
| # | Check | Result |
|---|-------|--------|
| 1 | Create DB, import 2022 dump; old `showmigrations` shows axes 0009 and editor 0011 unapplied | PASS (recorded in logs/01) |
| 2 | OLD `migrate` brings the 2022 schema to production schema | PASS: applies only `axes.0009_add_session_hash`, `editor.0011_specitem_created_at` (a naive-datetime RuntimeWarning for created_at default, harmless, pre-existing) |
| 3 | Populate | PASS |
| 4 | OLD exports/HTML/fingerprint | 2 ZIPs (6 members each), 26 spec-item exports (13 normal CSV + 13 latex), 14 HTML pages saved |
| 5 | NEW `showmigrations`, `migrate --plan`, `migrate` | PASS: plan is exactly `axes.0010_accessattemptexpiration` (Create model AccessAttemptExpiration); applied OK; `check` clean |
| 6a | editor_* row dumps and `CHECKSUM TABLE` identical across migrate | PASS (all 6 editor tables identical) |
| 6b | Other table changes by the migration | only: django_migrations 40->41 (axes 0010), new table `axes_accessattemptexpiration` (0 rows), auth_permission 64->68 and django_content_type 16->17 (permissions/content type for the new axes model, created by post_migrate); django_session/axes_accesslog +1 each come from the OLD snapshot's force_login, which ran between the two fingerprints (not from the migration). No column or collation change to any existing table |
| 6c | OLD vs NEW exports | PASS: 41 identical files (all 12 ZIP member CSVs, all 26 spec-item CSV/latex exports, Content-Disposition headers JSON, ZIP name lists), 0 different. The raw ZIP files (2) were not compared (timestamps) |
| 6d | OLD vs NEW HTML | PASS: 14 of 14 pages differ only by the logout control (`<a href=logout>` -> POST form + csrf token, normalized); 0 other differences |
| 6e | Saved OLD session cookie under NEW code | PASS: GET /editor/ shows `rehearsal_owner` (checked before any password login) |
| 6f | Old PBKDF2 passwords log in via POST under NEW code | PASS: 4/4 return 302 and see the username; hashes transparently upgraded 260000 -> 1000000 iterations |
| 6g | axes AccessAttempt and honeypot LoginAttempt visible in /pnpAdmin/ as superuser | PASS: "1 access attempt" (rehearsal_writer) and "1 login attempt" (honeypot_visitor) listed |
| 7a | OLD code on migrated DB: `check`; `migrate --plan` | PASS: no issues; "No planned migration operations" |
| 7b | OLD `showmigrations` | shows axes 0001..0009 all [X] and simply does not list `0010_accessattemptexpiration` (unknown file; the row in django_migrations is ignored). No error |
| 7c | OLD export_project / spec-item exports / HTML vs original old/ | PASS: 55 files identical, 0 different (rollback HTML also has the original `<a href>` logout) |
| 7d | editor_* rows/checksums after rollback reads | PASS identical; only django_session/axes_accesslog grew |
| 7e | Users with upgraded (1,000,000) hash log in with OLD code | PASS: 4/4. The old code re-hashes them back to 260000 on login (its default is lower, so `must_update`) |
| 7f | OLD axes/honeypot with the axes-0010 schema | PASS: a failed login in the old code creates a normal AccessAttempt (2 rows; admin shows "2 access attempts"); old code does not use the new table (rows are not expired by it, see below) |
| 7g | Data written by NEW code read by OLD code: session cookie of a NEW-code login | PASS (authenticated under old code) |
| 7h | New release + 2 spec items (negative/large numbers, unicode, JSON, `#iref`) + new user written by NEW code, then exported by OLD code | PASS: 41 export files byte-identical to the NEW code's export of the same data (the write changed 7 files vs the earlier export, proving the check is real); new user (1M hash) logs in under old code |
| 8 | Cleanup | PASS: database dropped, worktree removed, `test_cordetfw_migration_test` never touched, test suite not run |

## Differences / surprises (all explained)
1. **Logout control** (14 HTML pages): intentional template change (GET link -> POST form), as expected.
2. **Existing browser sessions are invalidated for a user once their password hash is upgraded** (new code on first password login: 260000 -> 1000000; the session auth hash derives from the stored hash). Observed: after the NEW-code password logins the saved OLD owner cookie no longer authenticated (`new_session_old_cookie_after_pw`: username not shown), although it worked before the hash upgrade. Same on rollback (old code re-hashes back to 260000, cookies minted under the 1M hash would be invalidated for that user; cookies created while the hash was 1M and tested with the old code before any password login did work, see 7g). Effect: users with another open session are logged out when they or anybody else log in with their password anew. Harmless but expect some re-logins after cutover; no data impact.
3. After rollback the migration `axes.0010` stays applied and the table `axes_accessattemptexpiration` remains; old code ignores it. Leftover rows there (the new axes uses them for cool-off expiry; 0 rows in this run) are harmless to old code. A real DB restore is not needed for rollback in this scenario, but it was not run with AXES cool-off data present in the new table.
4. Import of the 2022 dump leaves AUTO_INCREMENT at 12, hence project ids 13/14 (not a defect).
5. Old stack emits SyntaxWarning (invalid escape sequences) on Python 3.12; the new tree does not (pre-existing, not a behavioural difference).

## Not verified
- 4-byte (emoji) characters: not tested (connection charset utf8 on both stacks; BMP only by design).
- The production `admin` user from the 2022 dump (216000-iteration hash): password unknown, so its login was not tested.
- Real production data volume/timing, `import_project` roundtrip, FW Profile external DB (mocked/unused), email, HTTPS/cookie-secure behaviour (test client does not enforce SESSION_COOKIE_SECURE), static files and the real WSGI server.
- Raw ZIP bytes (only extracted members compared, since ZIP timestamps differ).
- Behaviour of the old code with non-empty `axes_accessattemptexpiration` rows.
