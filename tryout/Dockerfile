FROM python:3.12-bookworm

WORKDIR /usr/src/app

# mysqlclient is built from source: the bookworm image provides gcc, pkg-config and
# the MariaDB/MySQL client headers (default-libmysqlclient-dev).
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt && pip check

EXPOSE 7000

COPY . .

RUN mkdir -p /tmp/cordet_22/temp
COPY ./dj_cordetfw_config.json /etc/dj_cordetfw_config.json

# The database readiness is handled by the compose healthcheck (depends_on: service_healthy).
CMD [ "/bin/bash", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:7000" ]
