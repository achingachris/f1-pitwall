"""Register the webhook URL with Telegram."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bot.instance import get_bot


class Command(BaseCommand):
    help = "Register the Telegram webhook URL. Run once after deploying."

    def add_arguments(self, parser):
        parser.add_argument(
            "url",
            help="Full webhook URL — e.g. https://pitwall.example.com/telegram/webhook/<secret>/",
        )

    def handle(self, *args, url: str, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        if not settings.TELEGRAM_WEBHOOK_SECRET or settings.TELEGRAM_WEBHOOK_SECRET not in url:
            raise CommandError(
                "URL must include the TELEGRAM_WEBHOOK_SECRET segment so the receiver can verify."
            )
        bot = get_bot()
        bot.remove_webhook()
        ok = bot.set_webhook(url=url, allowed_updates=["message", "callback_query"])
        if ok:
            self.stdout.write(self.style.SUCCESS(f"Webhook set to {url}"))
        else:
            raise CommandError("Telegram returned False from setWebhook.")
