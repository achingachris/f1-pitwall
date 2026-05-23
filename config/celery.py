import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("f1")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "sync-current-season-daily": {
        "task": "seasons.tasks.sync_current_season",
        "schedule": crontab(hour=3, minute=30),
    },
}
