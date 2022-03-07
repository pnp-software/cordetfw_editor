# How to run a test installation
The docker-compose file in this directory will create a running Cordet
FW Editor test system. **ONLY FOR TESTING!** It will map the code into the docker container -> It will akt the same, as you would run `python manage.py runserver` by yourself.

## Precondition
 * docker installed
 * docker-compose installed

## Start
> First start will fail, as the database setup takes some time.
> Just wait a few seconds and shut it down with docker-compose down

```sh
cd ./tryout
docker-compose up --build
```

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
docker-compose down
```
