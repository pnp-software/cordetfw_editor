# admin_honeypot (vendored)

Vendored copy of [django-admin-honeypot](https://github.com/dmpayton/django-admin-honeypot)
1.1.0 (MIT licence, see `LICENSE`, © Derek Payton). Upstream has had no release since 2018
and does not support Django ≥ 4.0. It is vendored so that the app label `admin_honeypot`,
its migrations and the `admin_honeypot_loginattempt` table (with existing data) stay
unchanged.

Local changes (behaviour-neutral, for Django 4.0+ compatibility):

- `urls.py`: `django.conf.urls.url()` → `django.urls.re_path()` (same regexes).
- `admin.py`, `models.py`, `views.py`: `ugettext[_lazy]` → `gettext[_lazy]`.
- `signals.py`: dropped the documentation-only `providing_args` argument.
- `django-upgrade --target-version 4.2`: `@admin.register` / `@admin.display` instead of
  attribute assignments (the dead `allow_tags` attributes went with them; output unchanged),
  `path('login/')` for `re_path(r'^login/$')`, `request.headers` for `META['HTTP_USER_AGENT']`.

The changelist output (escaped HTML links, as with upstream on Django >= 2.0) is pinned by
the test suite.
