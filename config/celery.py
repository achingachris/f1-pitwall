import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("f1")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Beat schedules live in the DB (django-celery-beat) and are editable at
# /admin/django_celery_beat/. Initial entries are seeded on first migrate
# by seasons.schedules.seed_schedules. The full historical backfill is
# a one-shot, not scheduled — run `python manage.py backfill_history
# --reverse` once per environment.
