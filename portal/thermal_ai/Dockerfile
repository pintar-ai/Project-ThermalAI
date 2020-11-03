FROM python:3.7-buster

MAINTAINER GMNX <azzam.cyber@gmail.com>

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt install -y netcat

# create the app user
RUN adduser --disabled-password --gecos '' app

# create the appropriate directories
ENV HOME=/home/app
ENV APP_HOME=/home/app/web
RUN mkdir $APP_HOME
WORKDIR $APP_HOME

# chown all the files to the app user
RUN chown -R app:app $APP_HOME

# change to the app user
USER app
ENV PATH="/home/app/.local/bin:${PATH}"

# Install dependent packages
RUN pip install --upgrade pip
RUN pip install Flask Flask-SQLAlchemy SQLAlchemy-Utils flask_login flask_mail psycopg2-binary gunicorn qrcode[pil] bcrypt phonenumbers python-dateutil

# copy project
COPY . $APP_HOME

# run entrypoint.sh
ENTRYPOINT ["/home/app/web/entrypoint.sh"]
