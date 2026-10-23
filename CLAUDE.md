# CordetFW Editor

Django app for editing CORDET framework specifications. Being migrated from
Django 3.2 to the current LTS on branch `upgrade/django-lts`; see
`docs/migration/` for the plan, dependency matrix and task tracker.

## Configuration

Production reads `/etc/dj_cordetfw_config.json` (settings.py, editor/views.py,
editor/ext_cats.py). Override the path with `CORDETFW_CONFIG_PATH`.
`cordetfw_editor/settings_test.py` generates a synthetic config automatically.
Category definitions live in `editor/static/json/configs.json`.

## Tests

Current stack (Python 3.12, Django 5.2 LTS):

    python3.12 -m venv .venv
    .venv/bin/pip install -r requirements.txt -r requirements-test.txt -c requirements-lock.txt
    .venv/bin/python -m pytest -q
    scripts/migration_gate.sh .venv        # full gate: checks, SQLite + MySQL, goldens, warnings

Reference baseline = the pre-migration production environment (Python 3.12.3, Django 3.2.0),
for comparing behaviour with the old stack:

    python3.12 -m venv .venv-baseline
    .venv-baseline/bin/pip install -r requirements-baseline.txt -r requirements-test-baseline.txt
    .venv-baseline/bin/python -m pytest -q   # expected: the tests changed during the migration fail

Production uses MySQL, so the suite must also pass on a disposable MySQL 8.0
server (case-insensitive collation; never point this at a real database):

    docker run -d --rm --name cordetfw-mysql-test -p 127.0.0.1:33306:3306 \
      -e MYSQL_ROOT_PASSWORD=rootpw-test -e MYSQL_USER=cftest -e MYSQL_PASSWORD=cftest-pw \
      mysql:8.0 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    docker exec cordetfw-mysql-test mysql -uroot -prootpw-test \
      -e "GRANT ALL ON \`test_cordetfw_migration_test\`.* TO 'cftest'@'%'"
    CORDETFW_TEST_MYSQL_PORT=33306 CORDETFW_TEST_MYSQL_USER=cftest CORDETFW_TEST_MYSQL_PASSWORD=cftest-pw \
      .venv-baseline/bin/python -m pytest -q --ds=cordetfw_editor.settings_test_mysql

Backend-dependent expectations use `tests/backend.py:is_mysql()`.

Golden files in `tests/golden/` were recorded with `UPDATE_GOLDEN=1` on the baseline. After a
reviewed change, promote only the reviewed `*.actual` files; never re-record everything blindly.

## Migration harness rules

1. The suite is a characterization suite: it pins CURRENT behaviour, including
   known bugs. Never change production code to make a test pass during the
   baseline phase.
2. A suspected bug is asserted as-is, marked `# KNOWN-ISSUE: <short id>` and
   recorded in `docs/migration/known-issues/`. It is fixed only after the
   migration, in its own change.
3. Assert app-authored strings exactly. For messages produced by Django itself
   (form/password validation, admin), assert that the error exists, not its
   wording.
4. During upgrades, a failing test means a regression: fix the code, not the
   test. A test expectation may change only for an explained upstream behaviour
   change, in the same commit, with a comment.
5. Never skip, xfail or delete a failing test to pass a gate.
6. Use `client.force_login(user)` in tests: axes' backend rejects
   `client.login()` because it passes no request. Real login is tested by
   POSTing to the login URL.
7. Mock only the external FW Profile MySQL database (`MySQLdb` in
   `editor/ext_cats.py`). Use the real cexprtk, tablib, import-export and
   templates.

## Fix-phase rules (known issues, after the characterization suite)

Plan and status: `docs/fixes/register.md` (one row per issue, track S = with the migration,
K = `fix/known-issues`), checked by `scripts/known_issue_check.py` (part of the gate).

1. One issue (or one tightly coupled group) per commit. Write the tests for the fixed behaviour
   first; they must fail on the old code.
2. A `# KNOWN-ISSUE: <id>` test changes only in the commit that fixes that id: replace the
   assertion and mark it `# FIXED: <id> (was: <old behaviour>)`. Set the register row to
   `FIXED in <commit>` in the same commit.
3. Every other failing test is a regression. Harness rules 3-7 above still apply.
4. Exports stay byte-identical and exports of the current production version must still import,
   unless the export itself is the fixed bug and the operator approved it. Page/golden changes
   are allowed only for the fixed id and are promoted one file at a time after review.
5. Track S (on `upgrade/django-lts`): no schema migrations (rollback runs the old code on the
   migrated database).
