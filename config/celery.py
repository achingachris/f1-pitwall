import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("f1")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Baseline: nightly incremental sync of the current season at 03:30 EAT.
    "sync-current-season-daily": {
        "task": "seasons.tasks.sync_current_season",
        "schedule": crontab(hour=3, minute=30),
    },
    # Race-weekend catcher: hourly on Saturday + Sunday (EAT) to pick up
    # sprint and race results within ~1h of the chequered flag. Idempotent —
    # after the race is synced each call is ~4 jolpica requests.
    "sync-current-season-race-weekend": {
        "task": "seasons.tasks.sync_current_season",
        "schedule": crontab(minute=0, day_of_week="sat,sun"),
    },
}
# Note: the full historical backfill is a one-shot, not scheduled. Run it
# once per environment with `python manage.py backfill_history --reverse`
# (or via the Celery task `seasons.tasks.backfill_history`) to fill the DB
# from the current year backwards to 1950.
