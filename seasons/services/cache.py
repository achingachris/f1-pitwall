from django.core.cache import cache
from django.utils.timezone import now


def bump_data_version() -> None:
    cache.set("f1:ver", now().isoformat())
