"""Rate-safe paginating client for the jolpica F1 API (Ergast-compatible).

jolpica (unauthenticated) caps at 4 req/s burst AND 500 req/hr sustained. We
enforce both:
  - Per-call 0.3s spacer keeps the burst under 4 req/s.
  - A sliding-window throttle keeps the hourly rate under 480 (leaving headroom).
  - On 429 we honor Retry-After when present; otherwise exponential backoff.
"""

import logging
import time
from collections import deque
from typing import Any, Iterator

from django.conf import settings

import requests

log = logging.getLogger(__name__)

_BURST_SPACER_SECONDS = 0.3
_MAX_RETRIES = 7  # 1+2+4+8+16+32+64 = 127s of backoff in the worst case
_PAGE_SIZE = 100

# Sliding-window hourly throttle.
_HOURLY_CAP = 480  # stay safely under jolpica's 500/hr ceiling
_WINDOW_SECONDS = 3600.0
_RECENT_CALLS: deque[float] = deque()


class JolpicaError(Exception):
    """Raised when jolpica returns a non-recoverable error."""


def _throttle() -> None:
    """Block until we are below the hourly request cap."""
    now = time.monotonic()
    while _RECENT_CALLS and now - _RECENT_CALLS[0] > _WINDOW_SECONDS:
        _RECENT_CALLS.popleft()
    if len(_RECENT_CALLS) >= _HOURLY_CAP:
        sleep_for = _WINDOW_SECONDS - (now - _RECENT_CALLS[0]) + 0.5
        log.warning("jolpica hourly cap reached, sleeping %.0fs", sleep_for)
        time.sleep(sleep_for)
        now = time.monotonic()
        while _RECENT_CALLS and now - _RECENT_CALLS[0] > _WINDOW_SECONDS:
            _RECENT_CALLS.popleft()
    _RECENT_CALLS.append(time.monotonic())


def _retry_after(response: requests.Response, attempt: int) -> int:
    """Use the server's Retry-After header if present, otherwise exponential backoff."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return max(int(header), 1)
        except ValueError:
            pass
    return 2**attempt


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.JOLPICA_BASE}/{path}.json"
    headers = {"User-Agent": settings.JOLPICA_USER_AGENT}
    for attempt in range(_MAX_RETRIES):
        _throttle()
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code == 429:
            backoff = _retry_after(r, attempt)
            log.warning(
                "jolpica 429 on %s (attempt %s/%s), sleeping %ss",
                path,
                attempt + 1,
                _MAX_RETRIES,
                backoff,
            )
            time.sleep(backoff)
            continue
        if r.status_code >= 500:
            time.sleep(2**attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise JolpicaError(f"too many 429s on {path}")


def paginate(path: str, **params: Any) -> Iterator[dict[str, Any]]:
    """Yield each MRData payload in sequence, handling offset pagination."""
    params.setdefault("limit", _PAGE_SIZE)
    offset = 0
    while True:
        params["offset"] = offset
        payload = _get(path, params)
        md = payload["MRData"]
        yield md
        total = int(md["total"])
        lim = int(md["limit"])
        offset += lim
        time.sleep(_BURST_SPACER_SECONDS)  # ~3 req/s, under the 4/s burst ceiling
        if offset >= total:
            return


def fetch_all(path: str, **params: Any) -> list[dict[str, Any]]:
    """Return all MRData payloads as a list (convenience over paginate)."""
    return list(paginate(path, **params))
