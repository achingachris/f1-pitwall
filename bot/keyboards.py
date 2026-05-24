"""InlineKeyboardMarkup builders. Callback data is `:`-delimited."""

from telebot import types

from competitors.models import Constructor, Driver


def contenders_kb(year: int, current_kind: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            ("* " if current_kind == "driver" else "") + "Drivers",
            callback_data=f"cont:driver:{year}",
        ),
        types.InlineKeyboardButton(
            ("* " if current_kind == "constructor" else "") + "Constructors",
            callback_data=f"cont:constructor:{year}",
        ),
    )
    return kb


def standings_kb(
    year: int, kind: str, offset: int, total: int, page: int = 10
) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            ("* " if kind == "driver" else "") + "Drivers",
            callback_data=f"stand:driver:{year}:0",
        ),
        types.InlineKeyboardButton(
            ("* " if kind == "constructor" else "") + "Constructors",
            callback_data=f"stand:constructor:{year}:0",
        ),
    )
    nav: list[types.InlineKeyboardButton] = []
    if offset > 0:
        prev_off = max(0, offset - page)
        nav.append(
            types.InlineKeyboardButton("← Prev", callback_data=f"stand:{kind}:{year}:{prev_off}")
        )
    if offset + page < total:
        nav.append(
            types.InlineKeyboardButton(
                "Next →", callback_data=f"stand:{kind}:{year}:{offset + page}"
            )
        )
    if nav:
        kb.add(*nav)
    return kb


def round_nav_kb(year: int, number: int, total_rounds: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    row: list[types.InlineKeyboardButton] = []
    if number > 1:
        row.append(
            types.InlineKeyboardButton(
                f"← R{number - 1}", callback_data=f"round:{year}:{number - 1}"
            )
        )
    if number < total_rounds:
        row.append(
            types.InlineKeyboardButton(
                f"R{number + 1} →", callback_data=f"round:{year}:{number + 1}"
            )
        )
    if row:
        kb.add(*row)
    return kb


def driver_picker_kb(drivers: list[Driver]) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for d in drivers[:8]:
        kb.add(
            types.InlineKeyboardButton(
                f"{d.given_name} {d.family_name}" + (f" ({d.code})" if d.code else ""),
                callback_data=f"drv:{d.ref}",
            )
        )
    return kb


def team_picker_kb(constructors: list[Constructor]) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for c in constructors[:8]:
        kb.add(types.InlineKeyboardButton(c.name, callback_data=f"tm:{c.ref}"))
    return kb
