from django.apps import AppConfig
from django.db.models.signals import post_migrate


class SeasonsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "seasons"

    def ready(self):
        # Seed Pitwall's Beat schedules after django-celery-beat's tables
        # exist. Filtering on sender ensures we only run once, right after
        # django_celery_beat's migrations.
        def _seed(sender, **kwargs):
            if sender.name != "django_celery_beat":
                return
            from seasons.schedules import seed_schedules

            seed_schedules()

        post_migrate.connect(_seed, dispatch_uid="seasons.seed_beat_schedules")
