#!/usr/bin/env bash
# Common migration gate: run from the repo root.
#   scripts/migration_gate.sh [venv-dir]     (default: .venv)
# Requires the disposable MySQL test container described in CLAUDE.md.
set -uo pipefail
VENV=${1:-.venv}
PY="$VENV/bin/python"
MYSQL_ENV=(CORDETFW_TEST_MYSQL_PORT=${CORDETFW_TEST_MYSQL_PORT:-33306}
           CORDETFW_TEST_MYSQL_USER=${CORDETFW_TEST_MYSQL_USER:-cftest}
           CORDETFW_TEST_MYSQL_PASSWORD=${CORDETFW_TEST_MYSQL_PASSWORD:-cftest-pw})
status=0
step() { echo "== $1"; shift; "$@" || { echo "!! FAILED: $*"; status=1; }; }

step "versions"        "$PY" -c 'import sys, django; print(sys.version.split()[0], "Django", django.get_version())'
step "pip check"       "$PY" -m pip check
step "django check"    "$PY" manage.py check --settings=cordetfw_editor.settings_test
step "migration drift" "$PY" manage.py makemigrations --check --dry-run --settings=cordetfw_editor.settings_test
step "pytest sqlite"   "$PY" -m pytest -q -p no:warnings
step "pytest mysql"    env "${MYSQL_ENV[@]}" "$PY" -m pytest -q -p no:warnings --ds=cordetfw_editor.settings_test_mysql
step "no golden diffs" bash -c '! find tests/golden -name "*.actual" | grep .'
step "known issues"   "$PY" scripts/known_issue_check.py
step "diff --check"    git diff --check HEAD
echo "== warnings by location (count, location, category)"
"$PY" -m pytest -q -W default 2>&1 | grep -E "^\s*/.*:[0-9]+: [A-Za-z]+Warning:" \
  | sed -E "s|^\s*||; s|$PWD/||; s|^\.venv[^/]*/lib/python[0-9.]+/site-packages/||; s|^([^:]+:[0-9]+): ([A-Za-z]+Warning):.*|\1 \2|" \
  | sort | uniq -c | sort -rn | head -30
[ $status -eq 0 ] && echo "GATE PASSED" || echo "GATE FAILED"
exit $status
