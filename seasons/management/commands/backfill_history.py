from datetime import date

from django.core.management.base import BaseCommand

from seasons.tasks import backfill_history


class Command(BaseCommand):
    help = "Backfill historical seasons. Runs synchronously by default."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=int, default=1950)
        parser.add_argument("--end", type=int, default=date.today().year)
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip years whose Season.last_synced is already set. "
            "Use this to resume a partial backfill without re-hitting jolpica.",
        )
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            help="Enqueue via Celery instead of running in-process.",
        )

    def handle(self, *args, start: int, end: int, skip_existing: bool, run_async: bool, **opts):
        if run_async:
            backfill_history.delay(start, end, skip_existing=skip_existing)
            self.stdout.write(self.style.SUCCESS(f"queued backfill {start}..{end}"))
        else:
            result = backfill_history(start, end, skip_existing=skip_existing)
            self.stdout.write(self.style.SUCCESS(result))
