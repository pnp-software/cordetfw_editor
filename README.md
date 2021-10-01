## Cordet FW Editor

 The Cordet FW Editor provides an environment where users define various kinds of specification items
 for their applications.
 The specification information is stored in a database held on a server.
 The processing of the specification data is done by a back-end running on the server.
 The access to the editor data is through a browser on a client machine.
 
 The Cordet FW Editor is currently available as an **alpha version**.

### Start-Up
- Install Django `python3 -m pip install Django`
- Install Django-Crispy-Forms `pip3 install django-crispy-forms`
- Install cexprtk `pip3 install cexprtk`
- Set up a mySQL server
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

### Deployment
The `requirement.txt` file contains the exact library versions.

#### Using Virtual Environment
- load `source path_to_venv/bin/activate` e.g. `source python-app-venv/bin/activate`
- save dependencies `pip3 freeze > requirements.txt` in the project root

#### Do the Deployment
1. merge `master` into `deploy`
2. push deploy to github
3. `ssh pnp@pnp-software.io`
4. `cd cordetfw_editor`
5. `git pull origin`
6. Import static resources and (if required) run the migration
  - `source python-app-venv/bin/activate`
  - `python3 manage.py migrate`
  - `python3 manage.py collectstatic`
  - `deactivate`
7. `sudo systemctl reload apache2.service`

#### Update `css`
Cordet FW Editor uses [tailwindcss](https://tailwindcss.com/) for its
UI design. Tailwind CSS is:

> A utility-first CSS framework packed with classes like `flex`,
> `pt-4`, `text-center` and `rotate-90` that can be composed to build
> any design, directly in your markup.

A purged and minimized styles.css version for this editor can be found
under `editor/static/css/styles.css`. Any changes to the design
requires a recreation of `styles.css` otherwise previously not used
classes will not be present.

To simplify this build process a docker file and a docker-compose file
is provided -> no need to install anything (except `docker` and
`docker-compose`).

##### Build Command
The following commands will automatically build the required
tailwindcss container, will bind all relevant folder and will start
the build process.

```sh
cd css_builder
docker-compose up --build
```

Example output:

```sh
Creating network "css_builder_default" with the default driver
Building tailwind
Step 1/6 : FROM node:16.10.0
 ---> 9c23a8242f8b
Step 2/6 : WORKDIR /work
 ---> Using cache
 ---> 80a983426e68
Step 3/6 : RUN npm install tailwindcss@2.2.16                 @tailwindcss/typography@0.4.1 @tailwindcss/forms@0.3.4                 @tailwindcss/line-clamp@0.2.1 @tailwindcss/aspect-ratio@0.2.1                 postcss@8.3.8                 autoprefixer@10.3.6
 ---> Using cache
 ---> 054edc1ef873
Step 4/6 : ENV NODE_ENV=production
 ---> Using cache
 ---> 74412c4ab3a3
Step 5/6 : VOLUME ["/work/templates", "/work/editor", "/work/src"]
 ---> Using cache
 ---> d34e89b5d8b1
Step 6/6 : CMD ["npx", "tailwindcss", "-i", "./src/styles.css", "-o", "./static/styles.css", "--minify", "-w"]
 ---> Using cache
 ---> 0e57bccbe9f4

Successfully built 0e57bccbe9f4
Successfully tagged css_builder_tailwind:latest
Creating tailwind ... done
Attaching to tailwind
tailwind    |
tailwind    | warn - You have enabled the JIT engine which is currently in preview.
tailwind    | warn - Preview features are not covered by semver, may introduce breaking changes, and can change at any time.
tailwind    |
tailwind    | Rebuilding...
tailwind    | Done in 603ms.
```

As long as this is not stopped with `Ctrl-c` changes to template HTML
files will trigger a rebuild of the `styles.css` file.

##### Teardown
The build stack can be removed with:

```sh
docker-compose down
```

#### Security

##### Check Version
Check python libraries verison and update to latest.

1. ssh to server
2. `cd cordetfw_editor`
3. load environment `source python-app-venv/bin/activate`
4. `pip list --outdated`
5. update listed packaged with `pip install -U PACKAGE_NAME`
6. update `requirements.txt` with `pip freeze > requirements.txt`
7. add update `requirements.txt` to git

> load `requirements.txt` with `pip install -r requirements.txt`

##### Deployment Checklist Django
Django provides a [deployment checklist](https://docs.djangoproject.com/en/3.0/howto/deployment/checklist/)

**Done**
* `SECRET_KEY` is loaded from configuration file
* `DEBUG` is loaded from configuration file but should be disabled
* `ALLOWED_HOSTS` set according to server ip/dns
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


