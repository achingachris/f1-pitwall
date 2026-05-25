from django.core.cache import cache
from django.utils.timezone import now

# Jolpica-backed views (contenders, standings-derived pages) read `f1:ver:data`.
# Telemetry-only pages also read `f1:ver:telemetry` so FastF1 syncs do not
# invalidate analytics caches (and vice versa).
DATA_VERSION_KEY = "f1:ver:data"
LEGACY_VERSION_KEY = "f1:ver"
TELEMETRY_VERSION_KEY = "f1:ver:telemetry"


def bump_data_version() -> None:
    ts = now().isoformat()
    cache.set(DATA_VERSION_KEY, ts)
    cache.set(LEGACY_VERSION_KEY, ts)  # transitional — older keys may still exist


def bump_telemetry_version() -> None:
    cache.set(TELEMETRY_VERSION_KEY, now().isoformat())
