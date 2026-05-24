"""Telegram HTML formatters. Every header is prefixed with the Pitwall wordmark."""

from datetime import date
from html import escape
from typing import Iterable

from django.db.models import Count, Min, Sum

from analytics.services import Contender, contenders, funstats, latest_standings_round
from analytics.services import most_improved as _most_improved
from bot.team_names import official_name
from competitors.models import Constructor, Driver
from results.models import Qualifying, Result, Standing
from seasons.models import Round, Season
from telemetry.services import queries as telemetry_queries
from web.nationalities import flag_emoji
from web.services.wiki import fetch_summary

WORDMARK = "<b>Pitwall</b>"


def _h(s: str) -> str:
    return escape(str(s))


def _header(title: str) -> str:
    return f"{WORDMARK} · <b>{_h(title)}</b>"


def _flag(nationality: str) -> str:
    """Flag emoji with trailing space, or empty string if nationality unknown."""
    f = flag_emoji(nationality or "")
    return f"{f} " if f else ""


def _driver_name(driver: Driver, short: bool = False) -> str:
    """`<flag> Family` (short) or `<flag> Lewis Hamilton` (full)."""
    flag = _flag(driver.nationality)
    name = driver.family_name if short else f"{driver.given_name} {driver.family_name}"
    return f"{flag}{_h(name)}"


def _team_name(constructor: Constructor, official: bool = True) -> str:
    """`<flag> Mercedes-AMG Petronas F1 Team` (official) or short form."""
    flag = _flag(constructor.nationality)
    name = official_name(constructor) if official else constructor.name
    return f"{flag}{_h(name)}"


def welcome() -> str:
    return (
        f"{WORDMARK} — F1 stats in your chat.\n\n"
        "<b>Commands</b> (shortcuts in <i>italics</i>):\n"
        "• <code>/contenders</code> <i>/c</i> — who can still win the title\n"
        "• <code>/standings</code> <i>/s</i> — driver / constructor standings\n"
        "• <code>/season</code> <i>/sn</i> — season calendar\n"
        "• <code>/round &lt;n&gt;</code> <i>/r</i> — per-GP analysis\n"
        "• <code>/driver &lt;name&gt;</code> <i>/d</i> — driver profile\n"
        "• <code>/team &lt;name&gt;</code> <i>/t</i> — team profile\n"
        "• <code>/improved</code> <i>/i</i> — most-improved driver + team\n"
        "• <code>/funstats</code> <i>/f</i> — fastest / slowest aggregates\n"
        "• <code>/topspeeds</code> <i>/ts</i> — top speed-trap (FastF1)\n"
        "• <code>/laps &lt;n&gt;</code> <i>/l</i> — race lap stints (FastF1)\n\n"
        "All commands accept an optional <code>[year]</code> argument."
    )


def format_contenders(year: int, kind: str, rows: Iterable[Contender]) -> str:
    rows = list(rows)
    label = "Drivers" if kind == "driver" else "Constructors"
    head = _header(f"{label} who can still win {year}")
    if not rows:
        return f"{head}\n\n<i>No data yet — sync the season first.</i>"
    # For constructor mode, look up the live Constructor objects so we can
    # render the sponsor-rich official name. One batch query.
    official_lookup: dict[str, str] = {}
    if kind == "constructor":
        refs = [c.ref for c in rows if c.ref]
        for c in Constructor.objects.filter(ref__in=refs):
            official_lookup[c.ref] = official_name(c)
    lines = [head, ""]
    for i, c in enumerate(rows, 1):
        gap = "—" if c.gap == 0 else f"+{c.gap:g}"
        display = official_lookup.get(c.ref, c.label)
        flag = _flag(c.nationality)
        lines.append(
            f"<b>{i:>2}.</b> {flag}{_h(display)} — <b>{c.points:g}</b> pts · "
            f"gap {gap} · max {c.max_attainable:g}"
        )
    lines.append("")
    lines.append(f"<i>{len(rows)} still mathematically alive.</i>")
    return "\n".join(lines)


def format_standings(year: int, kind: str, offset: int = 0, page: int = 10) -> str:
    latest = latest_standings_round(year, kind=kind)
    label = "Drivers" if kind == "driver" else "Constructors"
    head = _header(f"{label}' standings · {year}")
    if not latest:
        return f"{head}\n\n<i>No standings yet for {year}.</i>"
    qs = (
        Standing.objects.filter(round=latest, kind=kind)
        .select_related("driver", "constructor")
        .order_by("position")
    )
    total = qs.count()
    rows = list(qs[offset : offset + page])
    if not rows:
        return f"{head}\n\n<i>No rows in this range.</i>"
    lines = [head, f"<i>After R{latest.number} {_h(latest.name)}</i>", ""]
    for r in rows:
        if kind == "driver" and r.driver:
            who = _driver_name(r.driver)
        elif r.constructor:
            who = _team_name(r.constructor)
        else:
            who = "?"
        lines.append(f"<b>{r.position:>2}.</b> {who} — <b>{r.points:g}</b> pts · {r.wins}W")
    if total > offset + page:
        lines.append("")
        lines.append(f"<i>Showing {offset + 1}–{offset + len(rows)} of {total}.</i>")
    return "\n".join(lines)


def format_season(year: int) -> str:
    season = Season.objects.filter(year=year).first()
    if not season:
        return f"{_header(f'{year} season')}\n\n<i>Year not synced.</i>"
    rounds = list(season.rounds.select_related("circuit").order_by("number"))
    lines = [_header(f"{year} season — {len(rounds)} rounds"), ""]
    for r in rounds:
        sprint = "  [sprint]" if r.has_sprint else ""
        lines.append(f"<b>R{r.number:>2}</b> {r.date:%b %d} · {_h(r.name)}{sprint}")
    return "\n".join(lines)


def format_round(rnd: Round) -> str:
    head = _header(f"R{rnd.number} {rnd.name}")
    sub = f"<i>{_h(rnd.circuit.name)} · {rnd.date:%b %d, %Y}</i>"
    blocks = [head, sub]

    sessions = rnd.sessions
    if sessions:
        blocks.append("\n<b>Sessions</b> <i>(UTC)</i>")
        for label, dt in sessions:
            blocks.append(f"  {label:<13} {dt:%a %b %d · %H:%M}")

    race = list(
        rnd.results.filter(session="race")
        .select_related("driver", "constructor")
        .order_by("position")[:10]
    )
    if race:
        blocks.append("\n<b>Race (top 10)</b>")
        for r in race:
            blocks.append(
                f"<b>{r.position_text:>2}.</b> {_driver_name(r.driver, short=True)} "
                f"<i>({_team_name(r.constructor, official=False)})</i> · {r.points:g} pt"
            )

    if rnd.has_sprint:
        sprint = list(
            rnd.results.filter(session="sprint").select_related("driver").order_by("position")[:8]
        )
        if sprint:
            blocks.append("\n<b>Sprint (top 8)</b>")
            for r in sprint:
                blocks.append(
                    f"<b>{r.position_text:>2}.</b> {_driver_name(r.driver, short=True)} · {r.points:g}"
                )

    quali = list(rnd.qualifying.select_related("driver").order_by("position")[:5])
    if quali:
        blocks.append("\n<b>Qualifying (top 5)</b>")
        for q in quali:
            best = q.q3 or q.q2 or q.q1 or "—"
            blocks.append(
                f"<b>{q.position:>2}.</b> {_driver_name(q.driver, short=True)} · "
                f"<code>{_h(best)}</code>"
            )

    return "\n".join(blocks)


def format_driver(driver: Driver, year: int) -> str:
    flag = flag_emoji(driver.nationality)
    head = f"{WORDMARK} · {flag} <b>{_h(driver.full_name)}</b>"
    meta_bits = []
    if driver.code:
        meta_bits.append(f"<code>{_h(driver.code)}</code>")
    if driver.nationality:
        meta_bits.append(_h(driver.nationality))
    if driver.age is not None:
        meta_bits.append(f"{driver.age} yrs")
    if driver.date_of_birth:
        meta_bits.append(f"b. {driver.date_of_birth:%b %d, %Y}")
    meta = " · ".join(meta_bits)

    season_q = Result.objects.filter(driver=driver, round__season__year=year, session="race")
    s_totals = season_q.aggregate(pts=Sum("points"), starts=Count("id"))
    s_wins = season_q.filter(position=1).count()
    s_podiums = season_q.filter(position__lte=3).count()
    latest = latest_standings_round(year, kind="driver")
    s_pos = None
    if latest:
        standing = Standing.objects.filter(round=latest, kind="driver", driver=driver).first()
        s_pos = standing.position if standing else None

    constructors_this_year = list(
        Constructor.objects.filter(
            result__driver=driver, result__round__season__year=year
        ).distinct()
    )

    career_q = Result.objects.filter(driver=driver, session="race")
    c_totals = career_q.aggregate(pts=Sum("points"), starts=Count("id"))
    c_wins = career_q.filter(position=1).count()
    c_podiums = career_q.filter(position__lte=3).count()
    c_best = career_q.filter(position__isnull=False).aggregate(b=Min("position"))["b"]
    c_poles = Qualifying.objects.filter(driver=driver, position=1).count()
    c_fl = career_q.filter(fastest_lap_rank=1).count()
    seasons_n = career_q.values_list("round__season__year", flat=True).distinct().count()

    bio = fetch_summary(driver.url, fallback_title=driver.full_name)

    lines = [head]
    if meta:
        lines.append(f"<i>{meta}</i>")
    lines.append("")
    if bio.get("extract"):
        # Trim to ~3 sentences for chat readability.
        extract = bio["extract"]
        if len(extract) > 320:
            extract = extract[:317] + "…"
        lines.append(_h(extract))
        if bio.get("url"):
            lines.append(f'<a href="{_h(bio["url"])}">Read on Wikipedia →</a>')
        lines.append("")

    lines.append(f"<b>{year} season</b>")
    lines.append(
        f"Pos {s_pos or '—'} · {s_totals['pts'] or 0:g} pts · "
        f"{s_wins}W / {s_podiums}P · {s_totals['starts'] or 0} starts"
    )
    if constructors_this_year:
        team_links = ", ".join(_team_name(c) for c in constructors_this_year)
        lines.append(f"<i>Team: {team_links}</i>")

    lines.append("")
    lines.append(f"<b>Career</b> <i>({seasons_n} seasons synced)</i>")
    lines.append(
        f"{c_totals['starts'] or 0} starts · {c_totals['pts'] or 0:g} pts · "
        f"{c_wins}W / {c_podiums}P · {c_poles} pole(s) · {c_fl} FL · "
        f"best P{c_best if c_best else '—'}"
    )
    return "\n".join(lines)


def format_team(constructor: Constructor, year: int) -> str:
    flag = flag_emoji(constructor.nationality)
    flag_prefix = f"{flag} " if flag else ""
    head = f"{WORDMARK} · {flag_prefix}<b>{_h(official_name(constructor))}</b>"
    short_name = constructor.name
    short_line = (
        f"<i>also known as {_h(short_name)}</i>" if short_name != official_name(constructor) else ""
    )

    season_q = Result.objects.filter(
        constructor=constructor, round__season__year=year, session="race"
    )
    s_totals = season_q.aggregate(pts=Sum("points"), starts=Count("id"))
    s_wins = season_q.filter(position=1).count()
    s_podiums = season_q.filter(position__lte=3).count()
    latest = latest_standings_round(year, kind="constructor")
    s_pos = None
    if latest:
        standing = Standing.objects.filter(
            round=latest, kind="constructor", constructor=constructor
        ).first()
        s_pos = standing.position if standing else None

    drivers_this_year = list(
        Driver.objects.filter(result__constructor=constructor, result__round__season__year=year)
        .distinct()
        .order_by("family_name")
    )

    career_q = Result.objects.filter(constructor=constructor, session="race")
    c_totals = career_q.aggregate(pts=Sum("points"), starts=Count("id"))
    c_wins = career_q.filter(position=1).count()
    c_best = career_q.filter(position__isnull=False).aggregate(b=Min("position"))["b"]
    c_poles = Qualifying.objects.filter(constructor=constructor, position=1).count()
    c_fl = career_q.filter(fastest_lap_rank=1).count()
    seasons_n = career_q.values_list("round__season__year", flat=True).distinct().count()

    bio = fetch_summary(constructor.url, fallback_title=constructor.name)

    lines = [head]
    if short_line:
        lines.append(short_line)
    if constructor.nationality:
        lines.append(f"<i>{_h(constructor.nationality)} · {seasons_n} seasons synced</i>")
    lines.append("")
    if bio.get("extract"):
        extract = bio["extract"]
        if len(extract) > 320:
            extract = extract[:317] + "…"
        lines.append(_h(extract))
        if bio.get("url"):
            lines.append(f'<a href="{_h(bio["url"])}">Read on Wikipedia →</a>')
        lines.append("")

    lines.append(f"<b>{year} season</b>")
    lines.append(
        f"Pos {s_pos or '—'} · {s_totals['pts'] or 0:g} pts · "
        f"{s_wins}W / {s_podiums}P · {s_totals['starts'] or 0} entries"
    )
    if drivers_this_year:
        names = ", ".join(_driver_name(d) for d in drivers_this_year)
        lines.append(f"<i>Drivers:</i> {names}")

    lines.append("")
    lines.append(f"<b>Career</b>")
    lines.append(
        f"{c_totals['starts'] or 0} entries · {c_totals['pts'] or 0:g} pts · "
        f"{c_wins}W · {c_poles} pole(s) · {c_fl} FL · best P{c_best if c_best else '—'}"
    )
    return "\n".join(lines)


def format_improved(year: int) -> str:
    driver = _most_improved(year, constructor=False)
    team = _most_improved(year, constructor=True)
    head = _header(f"Most improved · {year}")
    lines = [head, ""]
    if driver:
        d_flag = _flag(driver.get("nationality", ""))
        lines.append(
            f"<b>Driver:</b> {d_flag}{_h(driver['label'])} — "
            f"<b>Δ {driver['delta']:+.2f}</b> pts/round"
        )
    if team:
        t_flag = _flag(team.get("nationality", ""))
        # Promote to official name if we know it.
        t_constructor = (
            Constructor.objects.filter(ref=team.get("ref", "")).first() if team.get("ref") else None
        )
        t_label = official_name(t_constructor) if t_constructor else team["label"]
        lines.append(
            f"<b>Constructor:</b> {t_flag}{_h(t_label)} — "
            f"<b>Δ {team['delta']:+.2f}</b> pts/round"
        )
    if not driver and not team:
        lines.append("<i>Not enough rounds played yet.</i>")
    return "\n".join(lines)


def format_funstats(year: int) -> str:
    data = funstats(year)
    head = _header(f"Fun stats · {year}")
    lines = [head, ""]
    fl = data["season_fastest_lap"]
    if fl:
        lines.append(
            f"<b>Season fastest lap:</b> <code>{_h(fl.fastest_lap_time)}</code> — "
            f"{_driver_name(fl.driver, short=True)} at {_h(fl.round.name)}"
        )
    per_gp = data["fastest_lap_per_gp"][:10]
    if per_gp:
        lines.append("")
        lines.append("<b>Fastest lap per GP (last 10):</b>")
        for r in per_gp[-10:]:
            lines.append(
                f"R{r.round.number:>2} {_h(r.round.name)} — "
                f"<code>{_h(r.fastest_lap_time)}</code> {_driver_name(r.driver, short=True)}"
            )
    slowest = data["slowest_finishers"][:5]
    if slowest:
        lines.append("")
        lines.append("<b>Slowest classified finishers (recent):</b>")
        for r in slowest[-5:]:
            lines.append(
                f"R{r.round.number:>2} {_h(r.round.name)} — P{r.position} "
                f"{_driver_name(r.driver, short=True)}"
            )
    top_speeds = telemetry_queries.season_top_speeds(year, limit=5)
    if top_speeds:
        lines.append("")
        lines.append("<b>Top speed-trap (FastF1, top 5):</b>")
        for row in top_speeds:
            lines.append(
                f"{_driver_name(row['driver'], short=True)} — "
                f"<b>{row['top_speed_kmh']:.1f}</b> km/h <i>({_h(row['round'].name)})</i>"
            )
        lines.append("<i>Full table: /topspeeds</i>")
    return "\n".join(lines)


def format_top_speeds(year: int) -> str:
    rows = telemetry_queries.season_top_speeds(year, limit=20)
    head = _header(f"Top speeds · {year}")
    if not rows:
        return (
            f"{head}\n\n<i>No FastF1 data for {year} yet. "
            "Telemetry sync (admin) needed to populate this.</i>"
        )
    lines = [
        head,
        "<i>Best speed-trap reading per driver across all race sessions.</i>",
        "",
    ]
    for i, row in enumerate(rows, 1):
        team = ""
        if row["constructor"]:
            team = f" <i>({_team_name(row['constructor'], official=False)})</i>"
        lines.append(
            f"<b>{i:>2}.</b> {_driver_name(row['driver'], short=True)}{team} — "
            f"<b>{row['top_speed_kmh']:.1f}</b> km/h "
            f"<i>at {_h(row['round'].name)}</i>"
        )
    return "\n".join(lines)


_COMPOUND_EMOJI = {
    "SOFT": "🟥",
    "MEDIUM": "🟨",
    "HARD": "⚪",
    "INTERMEDIATE": "🟩",
    "WET": "🟦",
}


def _compound_pill(compound: str) -> str:
    return _COMPOUND_EMOJI.get(compound.upper(), "⚫") if compound else "⚫"


def format_laps(rnd: Round) -> str:
    drivers = telemetry_queries.race_lap_series(rnd)
    head = _header(f"Lap by lap · R{rnd.number} {rnd.name}")
    if not drivers:
        return (
            f"{head}\n\n<i>No FastF1 race-lap data for this round yet. "
            "Telemetry sync (admin) needed.</i>"
        )
    fastest = min((d["best_seconds"] for d in drivers if d["best_seconds"]), default=None)
    lines = [
        head,
        f"<i>{_h(rnd.circuit.name)} · {rnd.date:%b %d, %Y}</i>",
        "",
        "<i>Drivers ordered by fastest race lap. Stints show compound · lap count.</i>",
        "",
    ]
    for d in drivers:
        delta = ""
        if fastest and d["best_seconds"] is not None and d["best_seconds"] != fastest:
            delta = f" (+{d['best_seconds'] - fastest:.3f})"
        stint_bits = " ".join(f"{_compound_pill(s.compound)}{s.laps_count}" for s in d["stints"])
        lines.append(
            f"{_driver_name(d['driver'], short=True)} — "
            f"<code>{d['best_seconds']:.3f}</code>{delta} · {stint_bits}"
        )
    return "\n".join(lines)


def driver_picker_text(query: str, drivers: Iterable[Driver]) -> str:
    return f"{WORDMARK} — Found multiple drivers for " f"<code>{_h(query)}</code>. Pick one:"


def team_picker_text(query: str, constructors: Iterable[Constructor]) -> str:
    return f"{WORDMARK} — Found multiple teams for " f"<code>{_h(query)}</code>. Pick one:"


def not_found(kind: str, query: str) -> str:
    return f"{WORDMARK} — No {kind} found matching <code>{_h(query)}</code>."


def current_year() -> int:
    return date.today().year
