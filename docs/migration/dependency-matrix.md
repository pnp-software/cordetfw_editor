# Dependency matrix

Upstream data gathered 2026-10-23 from PyPI metadata and changelogs. Target:
**Django 5.2 LTS** (5.2.18, supported until April 2028), Python 3.12 (unchanged
from production). Django 6.1 is newer but not LTS; 6.2 LTS is scheduled for
April 2027 and is the next migration target.

"Bridge" = version used while on Django 4.2 (isolated environment only, never deployed).

| Package | Production | Bridge (Django 4.2) | Final (Django 5.2) | Role | Notes / required changes |
| --- | --- | --- | --- | --- | --- |
| Django | 3.2 (3.2.0) | 4.2.30 | **5.2.18** | direct | First 3.2.0 → 3.2.25 (security patches) as its own gate |
| asgiref | 3.11.0 | transitive | transitive (lock) | transitive | Remove from direct requirements; Django pins the range |
| sqlparse | 0.5.5 | transitive | transitive (lock) | transitive | Same |
| pytz | 2025.2 | transitive of Django 3.2 only | **removed** | unused | No app import; Django ≥4 does not need it. Remove at 5.2 after `pip show -r` confirms no dependant |
| cexprtk | 0.4.2 | 0.4.2 | **0.4.2** (latest) | direct, native | cp312 manylinux wheel exists |
| mysqlclient | 2.2.7 | 2.2.7 | **2.3.0** | direct, native | sdist only: needs `pkg-config` + MySQL client headers on the server (already the case) |
| django-axes | 7.0.2 | 7.0.2 | **8.3.1** | direct | 8.1 adds migration `axes.0010_accessattemptexpiration` (third-party schema change, rehearse on MySQL). Re-verify the backend setting (`AxesBackend` vs `AxesStandaloneBackend`) and the cooloff/lockout tests |
| django-ipware / python-ipware | 7.0.1 / 3.0.0 | same | **8.0.0** / 4.1.1 | transitive of axes | Pulled in by axes; pin in the lock only |
| django-crispy-forms | 2.0 | 2.0 | **2.7** | direct | Not rendered anywhere (only `FormHelper` imported in `editor/forms.py`). Add **crispy-bootstrap4 2026.2** + `crispy_bootstrap4` app + `CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap4'` so `CRISPY_TEMPLATE_PACK` stays valid |
| django-import-export | 3.3.9 | **4.1.1** (supports Django 3.2–5.0, tablib 3.5.0) | **4.4.3** | direct | Export only (`editor/resources.py`). `dehydrate_<field>(self, obj)` is unchanged in 4.x, but field ordering and rendering of None/types changed: the export goldens are the contract. Do 3.3.9 → 4.1.1 **on Django 3.2** as its own unit |
| tablib | 3.5.0 | 3.5.0 | **3.10.0** | direct | Only CSV is used; required ≥3.7 by import-export ≥4.2 |
| diff-match-patch | 20241021 | transitive | transitive | transitive of import-export | |
| defusedxml, MarkupPy, odfpy, openpyxl, et_xmlfile, xlrd, xlwt, PyYAML | prod | transitive | **removed** | tablib format extras pulled by import-export 3.x | No xls/ods/yaml/html export is used. Disappear when import-export 4 no longer installs format extras |
| django-appconf | 1.2.0 | 1.2.0 | removed from direct list | transitive? | Not imported by the app. Confirm its dependant with `pip show`; drop if none |
| setuptools | 80.10.2 | | not a runtime requirement | build tool | Not imported by app or apps (`pkg_resources` grep empty). Keep out of runtime requirements |
| django-admin-honeypot | 1.1.0 (2018, dead) | **vendored** | **vendored** | direct | See decision below |
| pytest / pytest-django / pytest-cov | n/a | 8.3.5 / 4.8.0 / 5.0.0 | 9.1.1 / 4.14.0 / 7.1.0 | test | 4.8.0 is the last pytest-django supporting Django 3.2 |
| django-upgrade | n/a | 1.33.0 (tool venv) | tool | tool | Not a project requirement |

## Decision: django-admin-honeypot

Upstream 1.1.0 was last released in 2018 (classifiers stop at Django 2.0). The only
fork, `django-admin-honeypot-updated-2021` 1.2.0, stops at Django 3.2. Neither supports
Django 4.2+.

**Vendor the package as a local app `admin_honeypot/`** (MIT licence, keep the LICENSE
file and attribution), with the minimal changes needed for Django 4.2/5.2 (`url()` →
`re_path()`, `ugettext*` → `gettext*`, other removed APIs).

Why: it keeps the same app label `admin_honeypot`, the same migrations and the same
`admin_honeypot_loginattempt` table and data. It also keeps the same `/admin/` decoy page and templates,
and the `LoginAttempt` admin page in `/pnpAdmin/`. No data migration, no behaviour change, and
the honeypot tests pass unchanged. The vendored code is first introduced on Django
3.2 as an identical copy (gate), then patched.

## Upgrade order (one gate each)

1. Behaviour-neutral warning fixes (raw strings) — Django 3.2.0
2. Django 3.2.0 → 3.2.25
3. Vendor admin_honeypot (identical copy), remove the package
4. django-import-export 3.3.9 → 4.1.1 (still Django 3.2): goldens must match
5. Django 4.2.30 (+ django-upgrade 4.2, remove nothing else)
6. Django 5.2.18 (USE_L10N removal with identical output, POST logout)
7. crispy 2.7 + crispy-bootstrap4
8. axes 8.3.1 / ipware 8
9. import-export 4.4.3 + tablib 3.10.0
10. mysqlclient 2.3.0, remove pytz/appconf/setuptools/asgiref/sqlparse from direct requirements, test tools
11. Exact pins + `requirements-lock.txt`
