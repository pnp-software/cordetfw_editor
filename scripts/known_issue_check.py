#!/usr/bin/env python3
"""Check docs/fixes/register.md against the KNOWN-ISSUE / FIXED markers in tests/.

Run from the repo root (stdlib only); exits 1 with one message per problem.
"""
import re
import sys
from pathlib import Path

REGISTER = Path('docs/fixes/register.md')
TESTS = Path('tests')
MARKER = re.compile(r'\b(KNOWN-ISSUE|FIXED):[ \t]*([A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9])')


def parse_register():
    rows = []
    for line in REGISTER.read_text().splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 7 or cells[0] in ('id', '---') or set(cells[0]) <= {'-', ' '}:
            continue
        rid, aliases, doc, tests, track, status, decision = cells
        alias_list = [] if aliases in ('', '—') else [a.strip() for a in aliases.split(',')]
        rows.append({'id': rid, 'names': [rid] + alias_list, 'tests': tests, 'track': track,
                     'status': status, 'decision': decision})
    return rows


def collect_markers():
    found = {'KNOWN-ISSUE': {}, 'FIXED': {}}
    for path in sorted(TESTS.rglob('*.py')):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for kind, mid in MARKER.findall(line):
                found[kind].setdefault(mid, []).append('%s:%d' % (path, n))
    return found


def main():
    rows = parse_register()
    markers = collect_markers()
    known, fixed = markers['KNOWN-ISSUE'], markers['FIXED']
    problems = []
    all_names = {n: r for r in rows for n in r['names']}

    for mid, where in sorted(known.items()):
        if mid not in all_names:
            problems.append('KNOWN-ISSUE marker "%s" (%s) is not a register id or alias' % (mid, where[0]))
    for mid, where in sorted(fixed.items()):
        row = all_names.get(mid)
        if row is None or not row['status'].startswith('FIXED'):
            problems.append('FIXED marker "%s" (%s) is not a register row with FIXED status' % (mid, where[0]))

    for r in rows:
        is_fixed = r['status'].startswith('FIXED')
        upstream = 'upstream' in r['decision']
        has_known = any(n in known for n in r['names'])
        has_fixed = any(n in fixed for n in r['names'])
        if is_fixed and not upstream:
            if has_known:
                problems.append('%s is FIXED but still has a KNOWN-ISSUE marker' % r['id'])
            if not has_fixed:
                problems.append('%s is FIXED but has no FIXED marker in tests/' % r['id'])
        elif r['status'].startswith('OPEN') and not has_known and r['tests'] != '—':
            problems.append('%s is OPEN with tests "%s" but has no KNOWN-ISSUE marker' % (r['id'], r['tests']))
        if r['track'] == '?':
            problems.append('%s has no track assigned' % r['id'])

    n_open = sum(r['status'].startswith('OPEN') for r in rows)
    n_fixed = sum(r['status'].startswith('FIXED') for r in rows)
    print('known issues: %d rows (%d open, %d fixed), %d KNOWN-ISSUE ids, %d FIXED ids'
          % (len(rows), n_open, n_fixed, len(known), len(fixed)))
    for p in problems:
        print('ERROR: ' + p)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
