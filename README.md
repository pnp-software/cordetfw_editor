## Cordet FW Editor

 The Cordet FW Editor provides an environment where users define various kinds of specification items
 for their applications.
 The specification information is stored in a database held on a server.
 The processing of the specification data is done by a back-end running on the server.
 The access to the editor data is through a browser on a client machine.

 Release 1.0.0 of the editor has been in use for some time at P&P Software GmbH.

### Start-Up
- Python 3.12, Django 5.2 LTS. Install the pinned dependencies into a virtual environment
  (mysqlclient is built from source and needs `pkg-config` and the MySQL client headers):
  ```sh
  python3.12 -m venv .venv
  .venv/bin/pip install -r requirements.txt -c requirements-lock.txt
  ```
- Configuration is read from `/etc/dj_cordetfw_config.json` (override the path with `CORDETFW_CONFIG_PATH`)
  - Optional keys: `CSRF_TRUSTED_ORIGINS`, `AXES_LOCKOUT_PARAMETERS` (see `docs/migration/ROLLOUT.md`)
- Set up a MySQL server (8.0.11 or later; tested with 8.0 and 8.4)
- If no database is available for import:
  - Create database cordetfw
  - In cordetfw_editor directory, run: `python3 manage.py createsuperuser` and create the `admin` user with superuser rights
  - Start the server on localhost with: `python3 manage.py runserver`
  - Navigate to: `http://localhost:8000/editor/` and select `admin` to create the users, the projects, and the ValSets 
    (make sure that each project has at least one ValSet called `default`)
- If a database is available, import it 
- Start the server on localhost with: `python3 manage.py runserver`
- Navigate to: `http://localhost:8000/editor/`

### Implementation Notes
- STATICFILES_DIRS in `settings.py` contains an absolute path!
- For the customization of the auto-completion list (e.g. changing number of entries): see issue #6

### Tests
See `CLAUDE.md` ("Tests"): `.venv/bin/python -m pytest -q`, the MySQL run, and `scripts/migration_gate.sh`.
Install the test tools with `pip install -r requirements-test.txt`.

### Deployment
`requirements.txt` lists the direct dependencies with exact versions; `requirements-lock.txt` pins the
complete resolved set. Install with `pip install -r requirements.txt -c requirements-lock.txt`.
For the Django 5.2 upgrade itself follow `docs/migration/ROLLOUT.md`.

#### Using Virtual Environment
- load `source path_to_venv/bin/activate` e.g. `source python-app-venv/bin/activate`

#### Do the Deployment
1. `ssh <your host>`
2. `cd <editor_directory>`
3. `git pull origin`
4. Install the dependencies, import static resources and (if required) run the migration
  - `source python-app-venv/bin/activate`
  - `pip install -r requirements.txt -c requirements-lock.txt`
  - `python3 manage.py migrate --plan` (review), then `python3 manage.py migrate`
  - `python3 manage.py collectstatic`
  - `deactivate`
5. `sudo systemctl reload apache2.service`

#### Update `css`
The CSS for the editor is created in an external tool and is tailored for the editor. 
The description of the creation and customization procedure for the CSS is still TBD.

#### Security

##### Check Version
Check python libraries verison and update to latest.

Updates are made in a development environment, never directly on the server:

1. `pip list --outdated` in a development venv lists candidates (an inventory, not a to-do list)
2. Update one package (or one compatibility group) at a time in `requirements.txt`
3. Install into a fresh venv, run `scripts/migration_gate.sh` (tests on SQLite and MySQL, golden files)
4. Regenerate `requirements-lock.txt` from that venv (`pip freeze`, without the test tools) and commit both files
5. Deploy as above

##### Deployment Checklist Django
Django provides a [deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
(`python3 manage.py check --deploy`)

**Done**
* `SECRET_KEY` is loaded from configuration file
* `DEBUG` is loaded from configuration file but should be disabled
* `ALLOWED_HOSTS` is loaded from configuration file
* `CACHES` *not relevant for us?*
* `DATABASE` password is loaded from configuration file
* `EMAIL_BACKEND` *not relevant for us?*
* `STATIC_ROOT` and `STATIC_URL` is set
* `MEDIA_ROOT` and `MEDIA_URL` *no uploaded files*
* https enabled in apache2
* `CSRF_COOKIE_SECURE` is `True`
* `SESSION_COOKIE_SECURE` is `True`
* add logging to `/home/pnp/djangoLogging/info.log` in format
  `YYYY-MM-DDTHH:MM:SS+0000|level|modul|message`
* run `sudo mysql_secure_installation`
* add `bind-address=127.0.0.1` in `/etc/mysql/conf.d/mysql.cnf` under `[mysql]`
  restart with `sudo /etc/init.d/mysql restart`

**To Do**
* Performance optimization chapter in deployment checklist
* Error reporting per mail and customize error views not done


Additional list: [Django Secrity Tips](https://snyk.io/blog/django-security-tips/)
* *check* use a secure django version
* *check* throttle user authentications
* *check* protect source code
* *check* use raw queries and custom SQL with caution
* *done* use HTTPS
* *not done* headers (more privacy than security?)
* *done* cookies only over https
* *check* user upload (do we have?)
* *check* security risks of dependencies


[Security in the Django Application](https://www.pyscoop.com/security-in-the-django-application/)
* *check* SQL injection
* *check if logged* CRLF injection
* *check but no prio* timing attack
* *check but no prio* clickjacking attack
* *check* cross-site scripting
* *check* CSRF
* *check* HTTP strict transport security


[10 tips for making the Dajngo Admin more secure](https://opensource.com/article/18/1/10-tips-making-django-admin-more-secure)
* *done* use SSL
* *do* change Admin URL
* *do* use `django-admin-honeypot`
* *check* require stronger password
* *maybe* use two-factor authentication
* *check* use latest version of Django
* *done* never run `DEBUG` in production
* *check* remember your environment
* *check* check for errors with `python manage.py check --deploy`


