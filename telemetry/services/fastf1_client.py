"""Thin wrapper around FastF1.

FastF1 is intentionally imported lazily inside `load_session` so that the
package is not required for unit tests, management commands that don't touch
telemetry, or environments where pandas/numpy aren't installed yet.
"""

from __future__ import annotations

import logging
import os
import threading

from django.conf import settings

log = logging.getLogger(__name__)

# F1 live timing (FastF1's data source) only covers 2018 onwards. Older
# seasons stay jolpica-only — callers must guard with this constant.
FASTF1_MIN_YEAR = 2018

_cache_lock = threading.Lock()
_cache_ready = False


class FastF1Unavailable(RuntimeError):
    """Raised when telemetry is requested for a season FastF1 cannot serve."""


def _ensure_cache() -> None:
    """Configure FastF1's on-disk cache exactly once per process."""
    global _cache_ready
    with _cache_lock:
        if _cache_ready:
            return
        import fastf1  # local import; avoids importing pandas at module load

        cache_dir = settings.FASTF1_CACHE_DIR
        os.makedirs(cache_dir, exist_ok=True)
        fastf1.Cache.enable_cache(cache_dir)
        _cache_ready = True
        log.info("fastf1 cache enabled at %s", cache_dir)


def load_session(year: int, round_number: int, kind_code: str, *, laps: bool = True):
    """Load and return a FastF1 ``Session`` ready for read access.

    ``kind_code`` is FastF1's session identifier (``"FP1"``, ``"Q"``, ``"S"``,
    ``"SS"``, ``"R"``, ...). For convenience this is what
    ``telemetry.models.Session.FASTF1_CODES`` produces.

    Telemetry traces are NOT loaded by default — Phase 1 only needs lap-level
    aggregates (lap times, sectors, speed trap), which are cheap.
    """
    if year < FASTF1_MIN_YEAR:
        raise FastF1Unavailable(
            f"FastF1 only has data from {FASTF1_MIN_YEAR} onwards (got {year})."
        )

    _ensure_cache()
    import fastf1

    session = fastf1.get_session(year, round_number, kind_code)
    session.load(laps=laps, telemetry=False, weather=False, messages=False)
    return session
