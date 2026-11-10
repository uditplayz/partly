#!/bin/sh
# Usage: entrypoint.sh web | worker | beat | migrate
set -e
case "$1" in
  web)     exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${WEB_CONCURRENCY:-3}" --access-logfile - ;;
  worker)  exec celery -A config worker -l info --concurrency "${CELERY_CONCURRENCY:-2}" ;;
  beat)    exec celery -A config beat -l info --pidfile=/tmp/celerybeat.pid ;;
  migrate) exec python manage.py migrate --noinput ;;
  *)       exec "$@" ;;
esac
