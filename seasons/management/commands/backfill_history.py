from datetime import date

from django.core.management.base import BaseCommand

from seasons.tasks import backfill_history


class Command(BaseCommand):
    help = (
        "Enqueue a Celery task to backfill historical seasons. Requires a " "running Celery worker."
    )

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
            "--reverse",
            action="store_true",
            help="Iterate newest year first (end → start) instead of oldest first.",
        )

    def handle(
        self,
        *args,
        start: int,
        end: int,
        skip_existing: bool,
        reverse: bool,
        **opts,
    ):
        result = backfill_history.delay(start, end, skip_existing=skip_existing, reverse=reverse)
        self.stdout.write(
            self.style.SUCCESS(
                f"queued backfill_history({start}..{end}, skip_existing={skip_existing}, "
                f"reverse={reverse}) → {result.id}"
            )
        )
