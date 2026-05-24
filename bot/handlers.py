"""All Telegram command + callback handlers for Pitwall."""

import logging

from django.conf import settings

import telebot

from analytics.services import contenders
from bot import formatters, keyboards, resolvers
from competitors.models import Constructor, Driver
from results.models import Standing
from seasons.models import Round, Season

log = logging.getLogger(__name__)
event_log = logging.getLogger("bot.event")


def _log_message(message, label: str) -> None:
    """One-line audit record of an incoming message handler call.

    Routed via the `bot.*` logger family to `logs/bot.log` in production.
    Captures user id + username + chat id + the raw text so we have enough
    forensic detail without storing message bodies in the DB.
    """
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    text = getattr(message, "text", "") or ""
    event_log.info(
        "msg %s user=%s username=%s chat=%s text=%r",
        label,
        getattr(user, "id", "?"),
        getattr(user, "username", "") or "-",
        getattr(chat, "id", "?"),
        text[:200],
    )


def _log_callback(call, label: str) -> None:
    user = getattr(call, "from_user", None)
    event_log.info(
        "cb %s user=%s username=%s data=%r",
        label,
        getattr(user, "id", "?"),
        getattr(user, "username", "") or "-",
        (getattr(call, "data", "") or "")[:200],
    )


# Canonical command -> (aliases, menu description). Aliases are accepted as
# message commands but NOT shown in Telegram's "/" picker (which only lists
# the canonical names below).
COMMAND_SPEC: dict[str, tuple[list[str], str]] = {
    "start": (["h"], "Welcome + command list"),
    "contenders": (["c"], "Who can still win the championship"),
    "standings": (["s"], "Driver / constructor standings"),
    "season": (["sn", "cal"], "Season calendar"),
    "round": (["r"], "Per-GP analysis (e.g. /r 5)"),
    "driver": (["d"], "Driver profile (e.g. /d hamilton)"),
    "team": (["t"], "Team profile (e.g. /t mercedes)"),
    "improved": (["i", "imp"], "Most-improved driver + team"),
    "funstats": (["f", "fs"], "Fastest laps + slowest finishers"),
    "topspeeds": (["ts"], "Top speed-trap readings (FastF1)"),
    "laps": (["l"], "Race lap-by-lap stints (FastF1, e.g. /l 1)"),
    "help": ([], "Show this menu"),
    "sync": ([], "Trigger a current-season sync (admin only)"),
}


def _cmds(name: str) -> list[str]:
    """Canonical name + aliases for the @message_handler decorator."""
    aliases, _ = COMMAND_SPEC[name]
    return [name, *aliases]


def _parse_year_arg(parts: list[str], default: int) -> int:
    for p in parts:
        if p.isdigit() and 1950 <= int(p) <= 2100:
            return int(p)
    return default


def _parse_kind_arg(parts: list[str], default: str = "driver") -> str:
    lookup = {
        "driver": "driver",
        "drivers": "driver",
        "team": "constructor",
        "teams": "constructor",
        "constructor": "constructor",
        "constructors": "constructor",
    }
    for p in parts:
        if p.lower() in lookup:
            return lookup[p.lower()]
    return default


def _is_admin(user_id: int) -> bool:
    return user_id in (settings.TELEGRAM_ADMIN_IDS or [])


def register(bot: telebot.TeleBot) -> None:
    """Attach every handler to the given bot instance."""

    # /start, /help (alias: /h) -----------------------------------------------
    @bot.message_handler(commands=_cmds("start") + _cmds("help"))
    def _start(message):
        _log_message(message, "/start")
        bot.reply_to(message, formatters.welcome(), disable_web_page_preview=True)

    # /season [year] (aliases: /sn, /cal) -------------------------------------
    @bot.message_handler(commands=_cmds("season"))
    def _season(message):
        _log_message(message, "/season")
        parts = message.text.split()[1:]
        year = _parse_year_arg(parts, formatters.current_year())
        bot.reply_to(message, formatters.format_season(year))

    # /standings [drivers|teams] [year] (alias: /s) ---------------------------
    @bot.message_handler(commands=_cmds("standings"))
    def _standings(message):
        _log_message(message, "/standings")
        parts = message.text.split()[1:]
        kind = _parse_kind_arg(parts, "driver")
        year = _parse_year_arg(parts, formatters.current_year())
        _send_standings(bot, message.chat.id, year, kind, 0)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("stand:"))
    def _standings_cb(call):
        _log_callback(call, "stand")
        _, kind, year, offset = call.data.split(":")
        _edit_standings(bot, call, int(year), kind, int(offset))

    # /contenders [drivers|teams] [year] (alias: /c) --------------------------
    @bot.message_handler(commands=_cmds("contenders"))
    def _contenders(message):
        _log_message(message, "/contenders")
        parts = message.text.split()[1:]
        kind = _parse_kind_arg(parts, "driver")
        year = _parse_year_arg(parts, formatters.current_year())
        _send_contenders(bot, message.chat.id, year, kind)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("cont:"))
    def _contenders_cb(call):
        _log_callback(call, "cont")
        _, kind, year = call.data.split(":")
        _edit_contenders(bot, call, int(year), kind)

    # /improved [year] (aliases: /i, /imp) ------------------------------------
    @bot.message_handler(commands=_cmds("improved"))
    def _improved(message):
        _log_message(message, "/improved")
        parts = message.text.split()[1:]
        year = _parse_year_arg(parts, formatters.current_year())
        bot.reply_to(message, formatters.format_improved(year))

    # /funstats [year] (aliases: /f, /fs) -------------------------------------
    @bot.message_handler(commands=_cmds("funstats"))
    def _funstats(message):
        _log_message(message, "/funstats")
        parts = message.text.split()[1:]
        year = _parse_year_arg(parts, formatters.current_year())
        bot.reply_to(message, formatters.format_funstats(year))

    # /topspeeds [year] (alias: /ts) ------------------------------------------
    @bot.message_handler(commands=_cmds("topspeeds"))
    def _topspeeds(message):
        _log_message(message, "/topspeeds")
        parts = message.text.split()[1:]
        year = _parse_year_arg(parts, formatters.current_year())
        bot.reply_to(message, formatters.format_top_speeds(year))

    # /laps <n> [year] (alias: /l) --------------------------------------------
    @bot.message_handler(commands=_cmds("laps"))
    def _laps(message):
        _log_message(message, "/laps")
        parts = message.text.split()[1:]
        nums = [int(p) for p in parts if p.isdigit()]
        if not nums:
            bot.reply_to(message, "Usage: <code>/laps &lt;round&gt; [year]</code>")
            return
        number = nums[0]
        year = nums[1] if len(nums) > 1 and 1950 <= nums[1] <= 2100 else formatters.current_year()
        rnd = (
            Round.objects.filter(season__year=year, number=number).select_related("circuit").first()
        )
        if not rnd:
            bot.reply_to(message, f"No round {number} in {year}.")
            return
        bot.reply_to(message, formatters.format_laps(rnd))

    # /round <n> [year] (alias: /r) -------------------------------------------
    @bot.message_handler(commands=_cmds("round"))
    def _round(message):
        _log_message(message, "/round")
        parts = message.text.split()[1:]
        nums = [int(p) for p in parts if p.isdigit()]
        if not nums:
            bot.reply_to(message, "Usage: <code>/round &lt;number&gt; [year]</code>")
            return
        number = nums[0]
        year = nums[1] if len(nums) > 1 and 1950 <= nums[1] <= 2100 else formatters.current_year()
        _send_round(bot, message.chat.id, year, number)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("round:"))
    def _round_cb(call):
        _log_callback(call, "round")
        _, year, number = call.data.split(":")
        _edit_round(bot, call, int(year), int(number))

    # /driver <query> (alias: /d) ---------------------------------------------
    @bot.message_handler(commands=_cmds("driver"))
    def _driver(message):
        _log_message(message, "/driver")
        query = message.text.split(maxsplit=1)[1].strip() if len(message.text.split()) > 1 else ""
        if not query:
            bot.reply_to(message, "Usage: <code>/driver &lt;name or code&gt;</code>")
            return
        hits = resolvers.find_drivers(query)
        if not hits:
            bot.reply_to(message, formatters.not_found("driver", query))
            return
        if len(hits) == 1:
            bot.reply_to(
                message,
                formatters.format_driver(hits[0], formatters.current_year()),
                disable_web_page_preview=True,
            )
            return
        bot.reply_to(
            message,
            formatters.driver_picker_text(query, hits),
            reply_markup=keyboards.driver_picker_kb(hits),
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("drv:"))
    def _driver_cb(call):
        _log_callback(call, "drv")
        _, ref = call.data.split(":", 1)
        driver = Driver.objects.filter(ref=ref).first()
        if not driver:
            bot.answer_callback_query(call.id, "Driver not found.")
            return
        bot.edit_message_text(
            formatters.format_driver(driver, formatters.current_year()),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        bot.answer_callback_query(call.id)

    # /team <query> (alias: /t) -----------------------------------------------
    @bot.message_handler(commands=_cmds("team"))
    def _team(message):
        _log_message(message, "/team")
        query = message.text.split(maxsplit=1)[1].strip() if len(message.text.split()) > 1 else ""
        if not query:
            bot.reply_to(message, "Usage: <code>/team &lt;name&gt;</code>")
            return
        hits = resolvers.find_constructors(query)
        if not hits:
            bot.reply_to(message, formatters.not_found("team", query))
            return
        if len(hits) == 1:
            bot.reply_to(
                message,
                formatters.format_team(hits[0], formatters.current_year()),
                disable_web_page_preview=True,
            )
            return
        bot.reply_to(
            message,
            formatters.team_picker_text(query, hits),
            reply_markup=keyboards.team_picker_kb(hits),
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("tm:"))
    def _team_cb(call):
        _log_callback(call, "tm")
        _, ref = call.data.split(":", 1)
        constructor = Constructor.objects.filter(ref=ref).first()
        if not constructor:
            bot.answer_callback_query(call.id, "Team not found.")
            return
        bot.edit_message_text(
            formatters.format_team(constructor, formatters.current_year()),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        bot.answer_callback_query(call.id)

    # /sync (admin only) ------------------------------------------------------
    @bot.message_handler(commands=_cmds("sync"))
    def _sync(message):
        _log_message(message, "/sync")
        if not _is_admin(message.from_user.id):
            bot.reply_to(message, "Not authorised.")
            return
        from seasons.tasks import sync_current_season

        sync_current_season.delay()
        bot.reply_to(message, "Sync queued.")


def register_menu(bot: telebot.TeleBot) -> None:
    """Tell Telegram which commands to show in the chat's '/' picker.

    Only the canonical names are listed (aliases stay hidden — they work but
    don't clutter the menu). Call this from polling startup or via the
    `set_telegram_commands` management command; the webhook handler does NOT
    need to call it on every request.
    """
    menu_order = [
        "start",
        "contenders",
        "standings",
        "season",
        "round",
        "driver",
        "team",
        "improved",
        "funstats",
        "topspeeds",
        "laps",
        "help",
    ]
    bot.set_my_commands(
        [telebot.types.BotCommand(name, COMMAND_SPEC[name][1]) for name in menu_order]
    )


# ---- send / edit helpers shared by message + callback handlers ----------------


def _send_contenders(bot: telebot.TeleBot, chat_id: int, year: int, kind: str) -> None:
    rows = contenders(year, constructor=(kind == "constructor"))
    bot.send_message(
        chat_id,
        formatters.format_contenders(year, kind, rows),
        reply_markup=keyboards.contenders_kb(year, kind),
    )


def _edit_contenders(bot: telebot.TeleBot, call, year: int, kind: str) -> None:
    rows = contenders(year, constructor=(kind == "constructor"))
    bot.edit_message_text(
        formatters.format_contenders(year, kind, rows),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=keyboards.contenders_kb(year, kind),
    )
    bot.answer_callback_query(call.id)


def _send_standings(bot: telebot.TeleBot, chat_id: int, year: int, kind: str, offset: int) -> None:
    total = _standings_total(year, kind)
    bot.send_message(
        chat_id,
        formatters.format_standings(year, kind, offset=offset),
        reply_markup=keyboards.standings_kb(year, kind, offset, total),
    )


def _edit_standings(bot: telebot.TeleBot, call, year: int, kind: str, offset: int) -> None:
    total = _standings_total(year, kind)
    bot.edit_message_text(
        formatters.format_standings(year, kind, offset=offset),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=keyboards.standings_kb(year, kind, offset, total),
    )
    bot.answer_callback_query(call.id)


def _standings_total(year: int, kind: str) -> int:
    from analytics.services import latest_standings_round

    latest = latest_standings_round(year, kind=kind)
    if not latest:
        return 0
    return Standing.objects.filter(round=latest, kind=kind).count()


def _send_round(bot: telebot.TeleBot, chat_id: int, year: int, number: int) -> None:
    rnd = Round.objects.filter(season__year=year, number=number).select_related("circuit").first()
    if not rnd:
        bot.send_message(chat_id, f"No round {number} in {year}.")
        return
    total = Season.objects.filter(year=year).first().rounds.count()
    bot.send_message(
        chat_id,
        formatters.format_round(rnd),
        reply_markup=keyboards.round_nav_kb(year, number, total),
    )


def _edit_round(bot: telebot.TeleBot, call, year: int, number: int) -> None:
    rnd = Round.objects.filter(season__year=year, number=number).select_related("circuit").first()
    if not rnd:
        bot.answer_callback_query(call.id, "Round not found.")
        return
    total = Season.objects.filter(year=year).first().rounds.count()
    bot.edit_message_text(
        formatters.format_round(rnd),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=keyboards.round_nav_kb(year, number, total),
    )
    bot.answer_callback_query(call.id)
