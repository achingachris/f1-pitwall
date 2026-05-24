"""Single TeleBot instance shared by the polling worker and the webhook view."""

from django.conf import settings

import telebot

_bot: telebot.TeleBot | None = None


def get_bot() -> telebot.TeleBot:
    """Return the singleton TeleBot, constructing + registering handlers on first call."""
    global _bot
    if _bot is None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not set. Add it to .env after rotating via @BotFather."
            )
        _bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN, parse_mode="HTML", threaded=False)
        # Import here so handlers can do `from bot.instance import get_bot`.
        from bot import handlers  # noqa: F401

        handlers.register(_bot)
    return _bot
