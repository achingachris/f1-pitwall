from django.core.management.base import BaseCommand

from seasons.tasks import sync_year


class Command(BaseCommand):
    help = (
        "Enqueue a Celery task to sync schedule, results, qualifying, and "
        "standings for a given season. Requires a running Celery worker."
    )

    def add_arguments(self, parser):
        parser.add_argument("year", type=int)
        parser.add_argument(
            "--skip-results",
            action="store_true",
            help="Only refresh schedule + standings; skip per-round results/qualifying.",
        )

    def handle(self, *args, year: int, skip_results: bool, **opts):
        result = sync_year.delay(year, skip_results=skip_results)
        self.stdout.write(
            self.style.SUCCESS(
                f"queued sync_year({year}, skip_results={skip_results}) → {result.id}"
            )
        )
