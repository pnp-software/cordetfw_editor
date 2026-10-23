# Rollout and rollback: Django 5.2 LTS

Do not deploy without completing **Staging**. The Django 4.2 commits on the branch are bridge steps and are not
deployable versions.

## 0. Before the maintenance window

- [ ] Rehearse on a **sanitized copy of the production database**:
      `REHEARSAL_DUMP=/path/to/sanitized.sql python3 docs/migration/rehearsal/rehearse.py`. All checks must pass.
      The script prints every difference.
- [ ] Record the production table charset/collation for `docs/migration/baseline.md`:
      `SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='cordetfw';`
- [ ] Check whether `DATABASES.default.OPTIONS` in `/etc/dj_cordetfw_config.json` sets a charset. Without one,
      the new code keeps `utf8`, the same as today.
- [ ] Find out how TLS reaches Django. With Apache + mod_wsgi serving HTTPS directly, nothing is needed. With a separate
      TLS proxy, add `"CSRF_TRUSTED_ORIGINS": ["https://<host>"]` to the config file.
- [ ] Note the Apache vhost's `WSGIDaemonProcess … python-home=` (or `WSGIPythonHome`) and the current venv path.
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
   production server for mysqlclient 2.2.7).
3. With the new venv:
   ```sh
   CORDETFW_CONFIG_PATH=/etc/dj_cordetfw_config.json /path/to/venv-dj52/bin/python manage.py check --deploy
   /path/to/venv-dj52/bin/python manage.py showmigrations
   /path/to/venv-dj52/bin/python manage.py migrate --plan     # expect only axes.0010_accessattemptexpiration
   /path/to/venv-dj52/bin/python manage.py migrate
   /path/to/venv-dj52/bin/python manage.py collectstatic --noinput
   ```
4. Point the staging vhost's `python-home` at the new venv and reload Apache.
5. Browser walkthrough (note any network or console errors):
   - [ ] login, logout (button), password change, password reset mail
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
5. Switch `python-home` to the new venv and run `sudo systemctl reload apache2`.
6. Smoke test: login, project list, one export, logout, `/pnpAdmin/`. Watch the editor log (`LOG_FILE`) and the Apache error log.

## 3. Rollback

The rehearsal showed that the **old code runs unchanged on the migrated database**. The only schema change is an
extra axes table that the old code ignores. Passwords rehashed by the new code still work with the old code.

- **Quick rollback (no restore):** switch `python-home` back to the old venv, check out the previous commit
  (`8516c81` / the previous release), and reload Apache. Data written meanwhile is kept and readable by the old code.
  Users are logged out once more (password rehash back to 260000 iterations).
- **Full rollback (only if data is damaged):** restore `pre-dj52.sql`. Writes made since the backup are lost
  unless they are exported first (project ZIP exports).
- Leave `axes.0010` in place after a quick rollback. Do not run `migrate` with the old code (it has nothing to apply).

## 4. After the cutover

- Keep the old venv and the backup until the next release.
- Replace the README's former "pip install -U / pip freeze" update procedure with the pinned procedure
  (README "Security / Check Version").
- Start the follow-ups listed in `RELEASE_NOTES.md`.
