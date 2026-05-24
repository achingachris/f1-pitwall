"""Clear the Telegram webhook so polling can resume."""

from django.core.management.base import BaseCommand, CommandError

from bot.instance import get_bot


class Command(BaseCommand):
    help = "Clear the Telegram webhook (drops pending updates)."

    def handle(self, *args, **opts):
        try:
            ok = get_bot().remove_webhook()
        except RuntimeError as e:
            raise CommandError(str(e))
        if ok:
            self.stdout.write(self.style.SUCCESS("Webhook cleared."))
        else:
            self.stdout.write(self.style.WARNING("Telegram returned False from removeWebhook."))
