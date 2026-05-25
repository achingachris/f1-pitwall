from datetime import date

from django.core.cache import cache
from django.db.models import Count, Min, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from analytics import services as analytics
from competitors.models import Constructor, Driver
from results.models import Qualifying, Result, Standing
from seasons.models import Round, Season
from seasons.services import calendar as calendar_service
from telemetry.services import queries as telemetry_queries
from web.nationalities import country_code, flag_emoji
from web.services.wiki import fetch_summary


def _data_cache_ver() -> str:
    from seasons.services.cache import DATA_VERSION_KEY, LEGACY_VERSION_KEY

    return cache.get(DATA_VERSION_KEY) or cache.get(LEGACY_VERSION_KEY, "0")


def _telemetry_cache_ver() -> str:
    from seasons.services.cache import TELEMETRY_VERSION_KEY

    return cache.get(TELEMETRY_VERSION_KEY, "0")


def _standings_snapshot(year: int) -> int:
    latest = analytics.latest_standings_round(year, kind="driver")
    return latest.number if latest else 0


def _get_contenders(year: int, *, constructor: bool, use_cache: bool):
    """Load title contenders. Landing skips cache (same freshness as Telegram)."""
    if not use_cache:
        return analytics.contenders(year, constructor=constructor)
    kind = "team" if constructor else "driver"
    key = f"contenders:{kind}:{year}:{_data_cache_ver()}:r{_standings_snapshot(year)}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = analytics.contenders(year, constructor=constructor)
    if rows:
        cache.set(key, rows, timeout=60 * 60 * 24)
    return rows


def _template(request, full: str, partial: str) -> str:
    return partial if request.htmx else full


def about(request):
    return render(request, "web/about.html")


def _error_response(request, *, status: int, title: str, message: str, detail: str):
    return render(
        request,
        "web/error.html",
        {
            "status_code": status,
            "title": title,
            "message": message,
            "detail": detail,
        },
        status=status,
    )


def bad_request(request, exception):
    return _error_response(
        request,
        status=400,
        title="That request did not line up",
        message="The request reached Pitwall, but something in it could not be understood.",
        detail=(
            "Try the home page or a recent season link. If you followed a saved URL, "
            "the route or query string may have changed."
        ),
    )


def permission_denied(request, exception):
    return _error_response(
        request,
        status=403,
        title="That area is restricted",
        message="Pitwall understood the request, but this page is not open for your session.",
        detail=(
            "If you expected access, head back to the public pages for now. This app is "
            "still intentionally small and may not expose every internal route."
        ),
    )


def page_not_found(request, exception):
    return _error_response(
        request,
        status=404,
        title="This lap is not on the timing screen",
        message="The page you asked for does not exist, moved, or has not been built yet.",
        detail=(
            "Check the URL, start from the latest season, or try the Telegram bot if you "
            "were looking for standings, contenders, or race-weekend info."
        ),
    )


def server_error(request):
    return _error_response(
        request,
        status=500,
        title="The pit wall dropped the headset",
        message="Something broke while Pitwall was preparing this page.",
        detail=(
            "Give it a moment and try again. If it keeps happening, opening an issue with "
            "the page URL and what you were trying to do would be genuinely useful."
        ),
    )


def landing(request):
    # Match Telegram /contenders: always the calendar year, always a live DB read.
    year = date.today().year
    seasons = list(Season.objects.values_list("year", flat=True)[:30])

    drivers = _get_contenders(year, constructor=False, use_cache=False)
    teams = _get_contenders(year, constructor=True, use_cache=False)

    # Calendar context is intentionally NOT cached so countdowns stay fresh.
    live = calendar_service.current_race_weekend()
    upcoming = None if live else calendar_service.next_race_weekend()
    focus_round = live or upcoming
    focus_session = calendar_service.current_or_next_session(focus_round) if focus_round else None

    return render(
        request,
        "web/landing.html",
        {
            "year": year,
            "seasons": seasons,
            "top_drivers": drivers[:5],
            "top_teams": teams[:5],
            "drivers_alive": len(drivers),
            "teams_alive": len(teams),
            "live_round": live,
            "upcoming_round": upcoming,
            "focus_round": focus_round,
            "focus_session": focus_session,
        },
    )


def season(request, year: int):
    season_obj = get_object_or_404(Season, year=year)
    rounds = season_obj.rounds.select_related("circuit")
    return render(
        request,
        _template(request, "web/season.html", "web/partials/season_body.html"),
        {"season": season_obj, "rounds": rounds, "year": year},
    )


def round_detail(request, year: int, number: int):
    rnd = get_object_or_404(Round, season__year=year, number=number)
    race = (
        rnd.results.filter(session="race")
        .select_related("driver", "constructor")
        .order_by("position")
    )
    sprint = (
        rnd.results.filter(session="sprint")
        .select_related("driver", "constructor")
        .order_by("position")
        if rnd.has_sprint
        else []
    )
    quali = rnd.qualifying.select_related("driver", "constructor").order_by("position")
    has_laps = telemetry_queries.race_session(rnd) is not None
    return render(
        request,
        _template(request, "web/round.html", "web/partials/round_body.html"),
        {
            "year": year,
            "round": rnd,
            "race": race,
            "sprint": sprint,
            "quali": quali,
            "has_laps": has_laps,
        },
    )


def _standings_page_context(year: int, kind: str, latest: Round) -> dict:
    rows = (
        Standing.objects.filter(round=latest, kind=kind)
        .select_related("driver", "constructor")
        .order_by("position")
    )
    changes = analytics.standing_changes(year, kind=kind) or {}
    entity_id = "driver_id" if kind == "driver" else "constructor_id"
    return {
        "year": year,
        "kind": kind,
        "latest": latest,
        "show_movement": bool(changes),
        "rows": [
            {
                "standing": row,
                "movement": changes.get(getattr(row, entity_id)),
            }
            for row in rows
        ],
    }


def driver_standings(request, year: int):
    latest = analytics.latest_standings_round(year, kind="driver")
    if not latest:
        raise Http404("No standings yet")
    return render(
        request,
        _template(request, "web/standings.html", "web/partials/standings_body.html"),
        _standings_page_context(year, "driver", latest),
    )


def team_standings(request, year: int):
    latest = analytics.latest_standings_round(year, kind="constructor")
    if not latest:
        raise Http404("No standings yet")
    return render(
        request,
        _template(request, "web/standings.html", "web/partials/standings_body.html"),
        _standings_page_context(year, "constructor", latest),
    )


def driver_contenders(request, year: int):
    data = _get_contenders(year, constructor=False, use_cache=True)
    return render(
        request,
        _template(request, "web/contenders.html", "web/partials/contenders_body.html"),
        {"year": year, "kind": "driver", "rows": data},
    )


def team_contenders(request, year: int):
    data = _get_contenders(year, constructor=True, use_cache=True)
    return render(
        request,
        _template(request, "web/contenders.html", "web/partials/contenders_body.html"),
        {"year": year, "kind": "team", "rows": data},
    )


def most_improved(request, year: int):
    key = f"improved:{year}:{_data_cache_ver()}:r{_standings_snapshot(year)}"
    data = cache.get(key)
    if data is None:
        data = {
            "driver": analytics.most_improved(year, constructor=False),
            "team": analytics.most_improved(year, constructor=True),
        }
        cache.set(key, data, timeout=60 * 60 * 24)
    return render(
        request,
        _template(request, "web/improved.html", "web/partials/improved_body.html"),
        {"year": year, "data": data},
    )


def funstats(request, year: int):
    key = f"funstats:{year}:{_data_cache_ver()}:{_telemetry_cache_ver()}"
    data = cache.get(key)
    if data is None:
        data = analytics.funstats(year)
        data["top_speeds"] = telemetry_queries.season_top_speeds(year)
        data["has_telemetry"] = bool(data["top_speeds"])
        cache.set(key, data, timeout=60 * 60 * 24)
    return render(
        request,
        _template(request, "web/funstats.html", "web/partials/funstats_body.html"),
        {"year": year, "data": data},
    )


def round_laps(request, year: int, number: int):
    rnd = get_object_or_404(Round, season__year=year, number=number)
    drivers = telemetry_queries.race_lap_series(rnd)
    fastest = min((d["best_seconds"] for d in drivers if d["best_seconds"]), default=None)
    if fastest:
        for d in drivers:
            d["delta_to_fastest"] = (
                d["best_seconds"] - fastest if d["best_seconds"] is not None else None
            )
    return render(
        request,
        _template(request, "web/round_laps.html", "web/partials/round_laps_body.html"),
        {"year": year, "round": rnd, "drivers": drivers, "session_best": fastest},
    )


def driver_laps_modal(request, year: int, number: int, ref: str):
    rnd = get_object_or_404(Round, season__year=year, number=number)
    driver = get_object_or_404(Driver, ref=ref)
    laps = telemetry_queries.driver_lap_table(rnd, driver)
    return render(
        request,
        "web/partials/driver_laps_modal.html",
        {"year": year, "round": rnd, "driver": driver, "laps": laps},
    )


def _year_param(request, default: int | None = None) -> int:
    raw = request.GET.get("year")
    if raw and raw.isdigit():
        return int(raw)
    return default or date.today().year


def driver_modal(request, ref: str):
    driver = get_object_or_404(Driver, ref=ref)
    year = _year_param(request)

    season_results = (
        Result.objects.filter(driver=driver, round__season__year=year, session="race")
        .select_related("round", "constructor")
        .order_by("round__number")
    )
    totals = season_results.aggregate(pts=Sum("points"), starts=Count("id"))
    wins = season_results.filter(position=1).count()
    podiums = season_results.filter(position__lte=3).count()
    season_best = season_results.filter(position__isnull=False).aggregate(best=Min("position"))[
        "best"
    ]

    latest_round = analytics.latest_standings_round(year, kind="driver")
    standing = None
    if latest_round:
        standing = Standing.objects.filter(round=latest_round, kind="driver", driver=driver).first()

    constructors_this_year = list(
        Constructor.objects.filter(result__driver=driver, result__round__season__year=year)
        .distinct()
        .values_list("name", flat=True)
    )

    career_races = Result.objects.filter(driver=driver, session="race")
    career = career_races.aggregate(pts=Sum("points"), starts=Count("id"))
    career_wins = career_races.filter(position=1).count()
    career_podiums = career_races.filter(position__lte=3).count()
    career_best = career_races.filter(position__isnull=False).aggregate(best=Min("position"))[
        "best"
    ]
    career_poles = Qualifying.objects.filter(driver=driver, position=1).count()
    career_fastest_laps = career_races.filter(fastest_lap_rank=1).count()
    seasons_active = career_races.values_list("round__season__year", flat=True).distinct().count()

    recent = list(season_results.order_by("-round__number")[:5])
    bio = fetch_summary(driver.url, fallback_title=driver.full_name)

    return render(
        request,
        "web/partials/driver_modal.html",
        {
            "driver": driver,
            "year": year,
            "flag": flag_emoji(driver.nationality),
            "country_code": country_code(driver.nationality),
            "bio": bio,
            "season_points": totals["pts"] or 0,
            "season_starts": totals["starts"] or 0,
            "season_wins": wins,
            "season_podiums": podiums,
            "season_best": season_best,
            "standing": standing,
            "constructors_this_year": constructors_this_year,
            "career_points": career["pts"] or 0,
            "career_starts": career["starts"] or 0,
            "career_wins": career_wins,
            "career_podiums": career_podiums,
            "career_best": career_best,
            "career_poles": career_poles,
            "career_fastest_laps": career_fastest_laps,
            "seasons_active": seasons_active,
            "recent": recent,
        },
    )


def team_modal(request, ref: str):
    constructor = get_object_or_404(Constructor, ref=ref)
    year = _year_param(request)

    season_results = (
        Result.objects.filter(constructor=constructor, round__season__year=year, session="race")
        .select_related("round", "driver")
        .order_by("round__number")
    )
    totals = season_results.aggregate(pts=Sum("points"), starts=Count("id"))
    wins = season_results.filter(position=1).count()
    podiums = season_results.filter(position__lte=3).count()
    season_best = season_results.filter(position__isnull=False).aggregate(best=Min("position"))[
        "best"
    ]

    latest_round = analytics.latest_standings_round(year, kind="constructor")
    standing = None
    if latest_round:
        standing = Standing.objects.filter(
            round=latest_round, kind="constructor", constructor=constructor
        ).first()

    drivers_this_year = list(
        Driver.objects.filter(result__constructor=constructor, result__round__season__year=year)
        .distinct()
        .order_by("family_name")
    )

    career_races = Result.objects.filter(constructor=constructor, session="race")
    career = career_races.aggregate(pts=Sum("points"), starts=Count("id"))
    career_wins = career_races.filter(position=1).count()
    career_podiums = career_races.filter(position__lte=3).count()
    career_best = career_races.filter(position__isnull=False).aggregate(best=Min("position"))[
        "best"
    ]
    career_poles = Qualifying.objects.filter(constructor=constructor, position=1).count()
    career_fastest_laps = career_races.filter(fastest_lap_rank=1).count()
    seasons_active = career_races.values_list("round__season__year", flat=True).distinct().count()

    recent = list(season_results.order_by("-round__number")[:5])
    bio = fetch_summary(constructor.url, fallback_title=constructor.name)

    return render(
        request,
        "web/partials/team_modal.html",
        {
            "constructor": constructor,
            "year": year,
            "flag": flag_emoji(constructor.nationality),
            "country_code": country_code(constructor.nationality),
            "bio": bio,
            "season_points": totals["pts"] or 0,
            "season_starts": totals["starts"] or 0,
            "season_wins": wins,
            "season_podiums": podiums,
            "season_best": season_best,
            "standing": standing,
            "drivers_this_year": drivers_this_year,
            "career_points": career["pts"] or 0,
            "career_starts": career["starts"] or 0,
            "career_wins": career_wins,
            "career_podiums": career_podiums,
            "career_best": career_best,
            "career_poles": career_poles,
            "career_fastest_laps": career_fastest_laps,
            "seasons_active": seasons_active,
            "recent": recent,
        },
    )


def modal_close(request):
    return HttpResponse("")
