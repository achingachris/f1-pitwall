import logging
import os
import sys
import threading

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger(__name__)


class BotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bot"

    def ready(self):
        """Auto-start the Telegram poller in a daemon thread when runserver boots.

        Conditions (all must hold):
          - Invoked via `manage.py runserver` (not migrate, tests, shell, etc.)
          - TELEGRAM_BOT_TOKEN is set
          - RUN_BOT_WITH_SERVER is not "false" (default: on)
          - We're in the auto-reloader's child process, OR --noreload was passed
            (otherwise the bot would spawn twice).
        Daemon thread → dies cleanly when runserver restarts on file change.
        """
        if not _should_start_bot_thread():
            return
        if not settings.TELEGRAM_BOT_TOKEN:
            log.info("Pitwall bot: TELEGRAM_BOT_TOKEN not set; skipping auto-start.")
            return

        from bot.handlers import register_menu
        from bot.instance import get_bot

        try:
            bot = get_bot()
            try:
                bot.remove_webhook()
            except Exception:
                log.warning("Pitwall bot: remove_webhook failed (continuing).", exc_info=True)

            try:
                register_menu(bot)
            except Exception:
                log.warning("Pitwall bot: register_menu failed (continuing).", exc_info=True)

            thread = threading.Thread(
                target=bot.infinity_polling,
                kwargs={
                    "timeout": 20,
                    "long_polling_timeout": 20,
                    "skip_pending": True,
                    "restart_on_change": False,
                },
                daemon=True,
                name="pitwall-bot-poller",
            )
            thread.start()
            print("Pitwall bot polling started in background thread.", file=sys.stderr)
        except Exception:
            log.exception("Pitwall bot: failed to start polling thread")


def _should_start_bot_thread() -> bool:
    if "runserver" not in sys.argv:
        return False
    if os.environ.get("RUN_BOT_WITH_SERVER", "true").lower() in {"0", "false", "no"}:
        return False
    # Avoid the auto-reloader's parent process — it would spawn a duplicate poller.
    if "--noreload" in sys.argv:
        return True
    return os.environ.get("RUN_MAIN") == "true"
