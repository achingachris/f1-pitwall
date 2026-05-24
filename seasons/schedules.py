"""Seed Pitwall's Celery Beat schedules into django-celery-beat's DB tables.

Runs once per environment via the post_migrate signal registered in
SeasonsConfig.ready(). Uses get_or_create so admin edits to schedules
persist across deploys — adding a new entry here only inserts when the
PeriodicTask name doesn't already exist.
"""

import logging

log = logging.getLogger(__name__)


_SCHEDULES = [
    {
        "name": "sync-current-season-daily",
        "task": "seasons.tasks.sync_current_season",
        "cron": {"minute": "30", "hour": "3", "day_of_week": "*"},
        "description": "Incremental baseline sync — 03:30 EAT daily.",
    },
    {
        "name": "sync-current-season-race-weekend",
        "task": "seasons.tasks.sync_current_season",
        "cron": {"minute": "0", "hour": "*", "day_of_week": "sat,sun"},
        "description": "Race-weekend catcher — hourly Sat + Sun EAT.",
    },
]


def seed_schedules(sender=None, **kwargs):
    """post_migrate handler. Idempotent: each PeriodicTask is created only
    if its name is missing, so admin edits to cron/enabled state survive
    redeploy."""
    # Import inside the function so this module is importable before
    # django-celery-beat's app registry is ready (e.g. during ./manage.py
    # check before its migrations have run).
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    for entry in _SCHEDULES:
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute=entry["cron"]["minute"],
            hour=entry["cron"]["hour"],
            day_of_week=entry["cron"]["day_of_week"],
            day_of_month="*",
            month_of_year="*",
            timezone="Africa/Nairobi",
        )
        _, created = PeriodicTask.objects.get_or_create(
            name=entry["name"],
            defaults={
                "crontab": cron,
                "task": entry["task"],
                "description": entry["description"],
            },
        )
        if created:
            log.info("seeded beat schedule: %s → %s", entry["name"], entry["task"])
