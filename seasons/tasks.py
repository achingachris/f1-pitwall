import logging
from datetime import date

from django.utils.timezone import now

from celery import shared_task

from seasons.models import Season
from seasons.services.cache import bump_data_version
from seasons.services.jolpica import JolpicaError
from seasons.services.sync import (
    sync_qualifying,
    sync_results,
    sync_schedule,
    sync_standings,
    unsynced_completed_rounds,
)

log = logging.getLogger(__name__)


@shared_task
def sync_year(year: int, skip_results: bool = False) -> str:
    from seasons.models import Round  # local import keeps task module light

    sync_schedule(year)
    if not skip_results:
        for rnd in Round.objects.filter(season__year=year).order_by("number"):
            try:
                sync_results(rnd, "race")
                if rnd.has_sprint:
                    sync_results(rnd, "sprint")
                sync_qualifying(rnd)
            except JolpicaError as e:
                log.error("sync_year: %s R%s skipped: %s", year, rnd.number, e)
    sync_standings(year)
    Season.objects.filter(year=year).update(last_synced=now())
    bump_data_version()
    return f"synced {year}"


@shared_task
def sync_current_season() -> str:
    year = date.today().year
    sync_schedule(year)
    for rnd in unsynced_completed_rounds(year):
        sync_results(rnd, "race")
        if rnd.has_sprint:
            sync_results(rnd, "sprint")
        sync_qualifying(rnd)
    sync_standings(year)
    Season.objects.filter(year=year).update(last_synced=now())
    bump_data_version()
    return f"synced {year}"


@shared_task
def backfill_history(
    start: int = 1950,
    end: int | None = None,
    skip_existing: bool = False,
    reverse: bool = False,
) -> str:
    end = end or date.today().year
    from seasons.models import Round  # local import keeps task module light

    synced = skipped = failed = 0
    years = range(end, start - 1, -1) if reverse else range(start, end + 1)
    for year in years:
        if skip_existing and Season.objects.filter(year=year, last_synced__isnull=False).exists():
            log.info("backfill: %s already synced, skipping", year)
            skipped += 1
            continue
        try:
            sync_schedule(year)
            for rnd in Round.objects.filter(season__year=year).order_by("number"):
                try:
                    sync_results(rnd, "race")
                    if rnd.has_sprint:
                        sync_results(rnd, "sprint")
                    sync_qualifying(rnd)
                except JolpicaError as e:
                    log.error("backfill: %s R%s skipped: %s", year, rnd.number, e)
            sync_standings(year)
            Season.objects.filter(year=year).update(last_synced=now())
            log.info("backfill: %s done", year)
            synced += 1
        except JolpicaError as e:
            log.error("backfill: year %s skipped: %s", year, e)
            failed += 1
    bump_data_version()
    return f"backfilled {start}..{end}: synced={synced} skipped={skipped} failed={failed}"
