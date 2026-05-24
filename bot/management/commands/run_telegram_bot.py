"""Long-polling entry point. Use for dev; webhook is preferred in prod."""

import logging
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from bot.instance import get_bot

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Pitwall Telegram bot via long-polling (dev mode)."

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(
                self.style.WARNING(
                    "TELEGRAM_BOT_TOKEN is not set — the bot worker is exiting cleanly. "
                    "Set it in .env (after rotating via @BotFather) to enable the bot."
                )
            )
            sys.exit(0)

        bot = get_bot()
        # Drop any stale webhook so polling can take over.
        try:
            bot.remove_webhook()
        except Exception:
            log.exception("remove_webhook failed (continuing anyway)")

        # Register the "/" command menu with Telegram. Idempotent, safe to retry.
        from bot.handlers import register_menu

        try:
            register_menu(bot)
        except Exception:
            log.exception("register_menu failed (continuing anyway)")

        self.stdout.write(self.style.SUCCESS("Pitwall bot polling Telegram..."))
        bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
