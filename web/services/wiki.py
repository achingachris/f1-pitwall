"""Wikipedia REST API client for fetching short biography extracts + thumbnails.

Cached in Django's cache for 7 days because Wikipedia summaries don't change
often, and we don't want the modal to feel slow on second open.
"""

import logging
from typing import Any
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.cache import cache

import requests

log = logging.getLogger(__name__)

_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_TIMEOUT = 3.0  # keep modal latency low — biography is a nice-to-have
_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days


def _title_from_url(url: str) -> str:
    """Pull the Wikipedia title out of a /wiki/<title> URL."""
    if not url:
        return ""
    path = urlparse(url).path
    if "/wiki/" in path:
        return unquote(path.split("/wiki/", 1)[1])
    return ""


def fetch_summary(wiki_url: str, fallback_title: str = "") -> dict[str, Any]:
    """Return {'extract': str, 'thumbnail': str, 'url': str} or {} on failure.

    Uses fallback_title (e.g. driver full name) if wiki_url is empty.
    """
    title = _title_from_url(wiki_url) or fallback_title
    if not title:
        return {}

    cache_key = f"wiki:{title.replace(' ', '_')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            _API + requests.utils.quote(title, safe=""),
            headers={
                "User-Agent": getattr(settings, "JOLPICA_USER_AGENT", "f1app/1.0"),
                "Accept": "application/json",
            },
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            log.info("wiki: %s -> %s", title, r.status_code)
            cache.set(cache_key, {}, _CACHE_TTL // 7)  # short negative cache
            return {}
        data = r.json()
        result = {
            "extract": data.get("extract", "") or "",
            "thumbnail": (data.get("thumbnail") or {}).get("source", ""),
            "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", "") or wiki_url,
        }
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except requests.RequestException as e:
        log.info("wiki: %s failed: %s", title, e)
        return {}
