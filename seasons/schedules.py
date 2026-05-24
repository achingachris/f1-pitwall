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
    {
        "name": "sync-recent-telemetry-race-weekend",
        "task": "telemetry.tasks.sync_recent_telemetry",
        # :30 offset gives the on-the-hour jolpica sync time to create the
        # Round rows that telemetry depends on (drivers looked up by code).
        "cron": {"minute": "30", "hour": "*", "day_of_week": "sat,sun"},
        "description": "FastF1 telemetry catcher — hourly Sat + Sun EAT, "
        "half-hour offset from the jolpica sync.",
    },
    # ------------------------------------------------------------------ one-shots
    # The two entries below are disabled by default — they exist as
    # PeriodicTask rows only so admin users can fire them via the built-in
    # "Run selected tasks" action at /admin/django_celery_beat/periodictask/.
    # The cron is a placeholder (Feb 30 never fires).
    {
        "name": "backfill-history (one-shot, run from admin)",
        "task": "seasons.tasks.backfill_history",
        "cron": {"minute": "0", "hour": "0", "day_of_week": "*"},
        "description": "One-shot: fill every jolpica season newest → oldest. "
        "Select this row in admin and choose 'Run selected tasks'.",
        "enabled": False,
        "kwargs": {"reverse": True, "skip_existing": True},
    },
    {
        "name": "backfill-telemetry (one-shot, run from admin)",
        "task": "telemetry.tasks.backfill_telemetry",
        "cron": {"minute": "0", "hour": "0", "day_of_week": "*"},
        "description": "One-shot: fan out FastF1 telemetry for every 2018+ "
        "round. Heavy — leaves the worker busy for hours. Select this row "
        "in admin and choose 'Run selected tasks'.",
        "enabled": False,
    },
]


def seed_schedules(sender=None, **kwargs):
    """post_migrate handler. Idempotent: each PeriodicTask is created only
    if its name is missing, so admin edits to cron/enabled state survive
    redeploy."""
    # Import inside the function so this module is importable before
    # django-celery-beat's app registry is ready (e.g. during ./manage.py
    # check before its migrations have run).
    import json

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
        defaults = {
            "crontab": cron,
            "task": entry["task"],
            "description": entry["description"],
            "enabled": entry.get("enabled", True),
        }
        if entry.get("kwargs"):
            defaults["kwargs"] = json.dumps(entry["kwargs"])
        _, created = PeriodicTask.objects.get_or_create(name=entry["name"], defaults=defaults)
        if created:
            log.info("seeded beat schedule: %s → %s", entry["name"], entry["task"])
