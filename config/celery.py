"""Celery application. Tasks live in apps/notifications/tasks.py; the beat schedule is in
apps/notifications/beat.py and is installed into the database by a migration."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("partly")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
