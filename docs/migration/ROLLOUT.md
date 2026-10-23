# Rollout and rollback: Django 5.2 LTS

Do not deploy without completing **Staging**. The Django 4.2 commits on the branch are bridge steps and are not
deployable versions.

## 0. Before the maintenance window

- [x] Rehearsal on the production dump of 2026-10-21 passed (see `rehearsal/REPORT.md`). Repeat it with a fresh
      dump shortly before cutover: `REHEARSAL_DUMP=/path/to/dump.sql python3 docs/migration/rehearsal/rehearse.py`.
- [x] Production collation confirmed from that dump: all `editor_*` tables `utf8mb4_unicode_ci`.
- [ ] Check whether `DATABASES.default.OPTIONS` in `/etc/dj_cordetfw_config.json` sets a charset. Without one,
      the new code keeps `utf8`, the same as today.
- [ ] Find out how TLS reaches Django. With Apache + mod_wsgi serving HTTPS directly, nothing is needed. With a separate
      TLS proxy, add `"CSRF_TRUSTED_ORIGINS": ["https://<host>"]` to the config file.
- [ ] Note the Apache vhost's `WSGIDaemonProcess … python-home=` (or `WSGIPythonHome`) and the current venv path.
      Also grep the Apache config for `python-path` / `WSGIPythonPath`. If either points into the old venv's
      `site-packages`, the old libraries would load first: change it together with `python-home`.
- [ ] Check that the server has time zone data (`ls /usr/share/zoneinfo/UTC`). Django ≥ 4 uses the system tz
      database instead of `pytz`.
- [ ] Inform users that they will need to log in again once (password rehash), and that logout bookmarks no longer work.

## 1. Staging (copy of the production server setup)

1. Restore a recent production backup into the staging MySQL server.
2. Build a **new** venv next to the old one; never upgrade the old venv in place:
   ```sh
   cd <editor_directory>
   git fetch && git checkout upgrade/django-lts        # or the merged release tag
   python3.12 -m venv /path/to/venv-dj52
   /path/to/venv-dj52/bin/pip install -r requirements.txt -c requirements-lock.txt
   /path/to/venv-dj52/bin/pip check
   ```
   mysqlclient is built from source: it needs `pkg-config` and the MySQL client headers (already present on the
   production server for mysqlclient 2.2.7). For identical builds without internet access in production, build
   wheels once on staging, `pip wheel -r requirements.txt -c requirements-lock.txt -w wheels/`, and install
   them in production with `pip install --no-index --find-links wheels/ -r requirements.txt -c requirements-lock.txt`.
3. With the new venv:
   ```sh
   CORDETFW_CONFIG_PATH=/etc/dj_cordetfw_config.json /path/to/venv-dj52/bin/python manage.py check --deploy
   /path/to/venv-dj52/bin/python manage.py showmigrations
   /path/to/venv-dj52/bin/python manage.py migrate --plan     # expect only axes.0010_accessattemptexpiration
   /path/to/venv-dj52/bin/python manage.py migrate
   /path/to/venv-dj52/bin/python manage.py collectstatic --noinput
   ```
4. Point the staging vhost's `python-home` at the new venv and **restart** Apache (`systemctl restart apache2`;
   a reload is not enough for `WSGIPythonHome` in embedded mode). Confirm the new stack is serving: `/pnpAdmin/`
   shows the Django 5.2 admin (dark-mode toggle).
5. Browser walkthrough (note any network or console errors):
   - [ ] login **through the real external `https://` URL** (not localhost: this catches a missing
         `CSRF_TRUSTED_ORIGINS` behind a TLS proxy), logout (button), password change, password reset mail
   - [ ] project list for an owner, an RW user and an RO user; an RO user cannot edit
   - [ ] add / edit / copy / split / delete a spec item, history, find/replace, refresh of an external Model item
   - [ ] make a project release and an application release; release view of a list
   - [ ] export a project ZIP and spec-item CSV/LaTeX; compare them with exports from the old production
   - [ ] import spec items from CSV; import a project ZIP (as staff)
   - [ ] `/pnpAdmin/`: users, access attempts, honeypot login attempts (timestamps readable)
   - [ ] `/admin/` shows the decoy login; three wrong logins at `/editor/login/` show the lockout page
   - [ ] static files and styling load

## 2. Production cutover

1. Announce the window. Stop writes by putting Apache in maintenance mode, or briefly stopping the vhost.
2. **Take a backup** and check that it can be restored: `mysqldump --single-transaction --routines cordetfw > pre-dj52.sql`.
3. Build the new venv as in Staging step 2 (keep the old venv untouched).
4. `migrate --plan` (expect only `axes.0010`), `migrate`, `collectstatic --noinput` with the new venv.
5. Switch `python-home` (and `python-path`, if set) to the new venv and run `sudo systemctl restart apache2`.
6. Smoke test: login, project list, one export, logout, `/pnpAdmin/`. Watch the editor log (`LOG_FILE`) and the Apache error log.

## 3. Rollback

The rehearsal showed that the **old code runs unchanged on the migrated database**. The only schema change is an
extra axes table that the old code ignores. Passwords rehashed by the new code still work with the old code.

- **Quick rollback (no restore):** check out the previous commit (`8516c81` / the previous release), run
  `old-venv/bin/python manage.py collectstatic --noinput --clear` (cutover replaced the static admin files with the
  Django 5.2 versions), switch `python-home` (and `python-path`) back to the old venv, and restart Apache. Data
  written meanwhile is kept and readable by the old code (rehearsed on production data). Users are logged out once
  more (password rehash back to 260000 iterations).
- **Full rollback (only if data is damaged):** restore `pre-dj52.sql`. Writes made since the backup are lost
  unless they are exported first (project ZIP exports).
- Leave `axes.0010` in place after a quick rollback. Do not run `migrate` with the old code (it has nothing to apply).
  Its table stays empty as long as `AXES_USE_ATTEMPT_EXPIRATION` is not enabled; keep it disabled until rollback is
  no longer an option.

## 4. After the cutover

- Keep the old venv and the backup until the next release.
- Replace the README's former "pip install -U / pip freeze" update procedure with the pinned procedure
  (README "Security / Check Version").
- Start the follow-ups listed in `RELEASE_NOTES.md`.
