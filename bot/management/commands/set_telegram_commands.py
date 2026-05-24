"""Register (or refresh) the bot's '/' menu with Telegram."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bot.handlers import register_menu
from bot.instance import get_bot


class Command(BaseCommand):
    help = "Push the canonical command list to Telegram (the '/' picker menu)."

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        register_menu(get_bot())
        self.stdout.write(self.style.SUCCESS("Commands menu registered with Telegram."))
