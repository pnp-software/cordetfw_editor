# How to run a test installation
The docker-compose file in this directory will create a running Cordet
FW Editor test system. **ONLY FOR TESTING!** It will map the code into the docker container -> It will akt the same, as you would run `python manage.py runserver` by yourself.

## Precondition
 * docker installed
 * docker compose (v2) installed

## Start
The editor waits until the database reports healthy (first start initializes the database,
which takes a while).

```sh
cd ./tryout
docker compose up --build
```

MySQL runs as `mysql:8.4`; its data lives in `./mysql84_db_persist`. An older
`./mysql_db_persist` directory (from the previous unpinned `mysql` image) is not used.

What it does:
 * setup a MySQL database with user: testuser and password: testpw
 * setup PHPMyAdmin on port 7001
 * create a docker image with all python packages
 * run manage.py migrate
 * run manage.py runserver 0.0.0.0:7000
 * maps local source directory into the docker container -> all code changes will be accessible

## Access
Cordet FW Editor is accessible on http://localhost:7000/editor with user `admin` and password `admin`.

## Stop
```sh
cd ./tryout
docker compose down
```
