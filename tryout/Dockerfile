FROM python:3.9

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 7000

COPY . .

RUN mkdir /tmp/cordet_22 \
    && mkdir /tmp/cordet_22/temp
RUN echo "sleep 5; python manage.py migrate; python manage.py runserver 0.0.0.0:7000" > /tmp/bootstrap.sh \
    && chmod +x /tmp/bootstrap.sh
COPY ./dj_cordetfw_config.json /etc/dj_cordetfw_config.json

#CMD [ "python", "manage.py", "migrate", "&&", "python", "manage.py", "runserver", "0.0.0.0:7000" ]
CMD [ "/bin/bash", "/tmp/bootstrap.sh" ]
