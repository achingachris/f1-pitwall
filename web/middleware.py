"""Request-level access logging.

Logs one line per request via the `web.request` logger, which is routed to
`logs/web.log` in production (see `config/settings.py::LOGGING`). Skips the
static/healthcheck paths so the file stays useful at a glance.
"""

import logging
import time

log = logging.getLogger("web.request")

_SKIP_PREFIXES = ("/static/", "/favicon.ico")


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "-")


class RequestLogMiddleware:
    """Emit `METHOD PATH STATUS DURATION_MS ip=… ua="…"` per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        if request.path.startswith(_SKIP_PREFIXES):
            return response
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            '%s %s %s %dms ip=%s ua="%s"',
            request.method,
            request.get_full_path(),
            response.status_code,
            elapsed_ms,
            _client_ip(request),
            request.META.get("HTTP_USER_AGENT", "-")[:120],
        )
        return response
