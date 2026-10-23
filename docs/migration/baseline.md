# Migration baseline

Recorded 2026-10-23 on branch `upgrade/django-lts`, starting from `main` at `8516c81`.

## Production environment (provided by the operator)

| Item | Value |
| --- | --- |
| OS | Ubuntu 24.04 |
| Python | 3.12.3 |
| Django | 3.2 (3.2.0, not officially supported on Python 3.12, but in production use) |
| Database | MySQL 8.0.46 (Ubuntu package) |
| Web server | Apache + mod_wsgi |
| Packages | `requirements-baseline.txt` (exact `pip freeze`) |

Notable: `requirements.txt` is unpinned, and resolving it today does not
reproduce production. `tryout/Dockerfile` uses Python 3.9 and does not match
production. Production already runs django-crispy-forms 2.0 without a template
pack package (crispy is imported in `editor/forms.py`, but never rendered).

## Local baseline environment

`.venv-baseline` (Python 3.12.3 on the developer host, same as production)
installed from `requirements-baseline.txt` + `requirements-test.txt`;
`pip check` clean, `manage.py check` clean, `makemigrations --check` clean,
`MySQLdb` and `cexprtk` import.

## Baseline warnings (pre-existing)

- `SyntaxWarning: invalid escape sequence` in `editor/convert.py:75`,
  `editor/markdown.py:24,26,72`, `editor/templatetags/ref_filters.py:99,107`.
  Behaviour is identical (unknown escapes are kept literally). These will be fixed
  with raw strings in a behaviour-neutral commit, guarded by the suite.
- `RuntimeWarning`: naive default `datetime(2000, 1, 1)` for `SpecItem.created_at`.
- `RemovedInDjango40Warning`: `admin_honeypot/urls.py` uses `url()`.

## Test suite (frozen baseline, 2026-10-23)

| Backend | Result | Command |
| --- | --- | --- |
| SQLite (`:memory:`) | **1134 passed, 9 skipped** (MySQL-only tests) | `.venv-baseline/bin/python -m pytest -q` |
| MySQL 8.0.42 container, utf8mb4_unicode_ci | **1143 passed** | see CLAUDE.md |

Both are stable over repeated runs. Line coverage of `editor/` + `cordetfw_editor/`: **98%**.
`makemigrations --check`: no changes. `pip check`: clean.

- 59 golden files in `tests/golden/`: 33 rendered pages, 22 export files (ZIP members and CSV),
  5 auth/admin pages. They are byte-exact, and `.gitattributes` disables EOL conversion.
- **65 `KNOWN-ISSUE` ids** pinned as-is (see `known-issues/README.md`).
- **22 `EXPECTED-CHANGE` tests**: upstream behaviour changes that the named upgrade task must
  resolve explicitly:
  - bare datetime/admin timestamp rendering (USE_L10N)
  - CSRF Origin checking
  - Cross-Origin-Opener-Policy header
  - CSRF cookie length
  - GET logout
  - logout cookie flags
  - PBKDF2 iterations on login
  - FileResponse filename escaping
  - import-export number rendering
  - MySQL connection charset
  - password-reset-confirm widget markup

### Baseline warnings (-W default)

| Source | Warning | Planned resolution |
| --- | --- | --- |
| `editor/views.py:1088`, `editor/imports.py:49,62,75,98,118` | ResourceWarning: unclosed file | Post-migration fix (KNOWN-ISSUE), behaviour-neutral |
| `import_export/resources.py:1122` | `queryset` must be a named parameter | **Required for import-export 4**: call sites in `views.py:1108-1141` |
| `admin_honeypot` urls/views | `url()`, `ugettext()` removed in 4.0 | Vendored-honeypot task |
| Django 3.2 internals | `cgi`, `utcnow`, sqlite date converter, `getdefaultlocale` on Python 3.12 | Disappear with Django 4.2+ |
| `SpecItem.created_at` default, test data | naive datetime RuntimeWarning | KNOWN-ISSUE `naive-created-at-default`; not changed (schema) |
| `editor/convert.py`, `markdown.py`, `ref_filters.py` | SyntaxWarning invalid escape | Task 3.1 (raw strings, behaviour-neutral) |

## Pending: production DB collation

TODO (operator): the MySQL charset/collation of the PRODUCTION database has not been compared
with the test database yet. Run on production and record the values here:

    SELECT @@character_set_connection, @@collation_connection;
    SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_NAME = 'editor_specitem';
    SELECT COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME FROM information_schema.COLUMNS
      WHERE TABLE_NAME = 'editor_specitem' AND COLLATION_NAME IS NOT NULL;

Observed in the disposable MySQL 8.0 test database (server `--character-set-server=utf8mb4
--collation-server=utf8mb4_unicode_ci`, Django 3.2.0 connection): connection
`utf8mb3` / `utf8mb3_general_ci`; `editor_specitem` table and all text columns
`utf8mb4` / `utf8mb4_unicode_ci`. Pinned in `tests/test_db_backend.py`
(`test_connection_charset_and_collation`, `test_mysql_specitem_table_and_column_charset`).
If production differs (e.g. `utf8mb3_general_ci` columns, or a case-sensitive collation), the
query-ordering and uniqueness tests may behave differently there.
