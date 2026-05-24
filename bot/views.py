"""Webhook endpoint for production Telegram delivery."""

import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import telebot

from bot.instance import get_bot

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_webhook(request, secret: str):
    """Receive an Update payload from Telegram and dispatch it to handlers.

    The `secret` path segment must match settings.TELEGRAM_WEBHOOK_SECRET
    (constant-time compare). Mismatch returns 404 so we don't leak that the
    endpoint exists.
    """
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if not expected or not hmac.compare_digest(secret, expected):
        return HttpResponseNotFound()

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest()

    if not payload:
        # Empty body is treated as a no-op probe — 200 OK so monitoring doesn't alarm.
        return HttpResponse("")

    try:
        update = telebot.types.Update.de_json(payload)
        get_bot().process_new_updates([update])
    except Exception:
        # Never 500 on a webhook — Telegram retries and could DDOS us.
        log.exception("telegram webhook handler crashed")

    return HttpResponse("")
