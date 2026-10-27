#!/bin/sh
# Avvio del container web. exec: gunicorn diventa il processo principale e scrive
# il pidfile, che `manage.py modulo ... --riavvia` usa per mandargli SIGHUP.
set -e
python manage.py collectstatic --noinput
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --pid /tmp/gunicorn.pid
