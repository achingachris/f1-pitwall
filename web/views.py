from datetime import date

from django.core.cache import cache
from django.db.models import Count, Min, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from analytics import services as analytics
from competitors.models import Constructor, Driver
from results.models import Qualifying, Result, Standing
from seasons.models import Round, Season
from web.nationalities import country_code, flag_emoji
from web.services.wiki import fetch_summary


def _cache_ver() -> str:
    return cache.get("f1:ver", "0")


def _template(request, full: str, partial: str) -> str:
    return partial if request.htmx else full


def landing(request):
    year = date.today().year
    seasons = list(Season.objects.values_list("year", flat=True)[:30])

    ver = _cache_ver()
    drivers_key = f"contenders:driver:{year}:{ver}"
    teams_key = f"contenders:team:{year}:{ver}"
    drivers = cache.get(drivers_key)
    if drivers is None:
        drivers = analytics.contenders(year, constructor=False)
        cache.set(drivers_key, drivers, timeout=60 * 60 * 24)
    teams = cache.get(teams_key)
    if teams is None:
        teams = analytics.contenders(year, constructor=True)
        cache.set(teams_key, teams, timeout=60 * 60 * 24)

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
    return render(
        request,
        _template(request, "web/round.html", "web/partials/round_body.html"),
        {"year": year, "round": rnd, "race": race, "sprint": sprint, "quali": quali},
    )


def driver_standings(request, year: int):
    latest = analytics.latest_standings_round(year, kind="driver")
    if not latest:
        raise Http404("No standings yet")
    rows = Standing.objects.filter(round=latest, kind="driver").select_related("driver")
    return render(
        request,
        _template(request, "web/standings.html", "web/partials/standings_body.html"),
        {"year": year, "rows": rows, "kind": "driver", "latest": latest},
    )


def team_standings(request, year: int):
    latest = analytics.latest_standings_round(year, kind="constructor")
    if not latest:
        raise Http404("No standings yet")
    rows = Standing.objects.filter(round=latest, kind="constructor").select_related("constructor")
    return render(
        request,
        _template(request, "web/standings.html", "web/partials/standings_body.html"),
        {"year": year, "rows": rows, "kind": "constructor", "latest": latest},
    )


def driver_contenders(request, year: int):
    key = f"contenders:driver:{year}:{_cache_ver()}"
    data = cache.get(key)
    if data is None:
        data = analytics.contenders(year, constructor=False)
        cache.set(key, data, timeout=60 * 60 * 24)
    return render(
        request,
        _template(request, "web/contenders.html", "web/partials/contenders_body.html"),
        {"year": year, "kind": "driver", "rows": data},
    )


def team_contenders(request, year: int):
    key = f"contenders:team:{year}:{_cache_ver()}"
    data = cache.get(key)
    if data is None:
        data = analytics.contenders(year, constructor=True)
        cache.set(key, data, timeout=60 * 60 * 24)
    return render(
        request,
        _template(request, "web/contenders.html", "web/partials/contenders_body.html"),
        {"year": year, "kind": "team", "rows": data},
    )


def most_improved(request, year: int):
    key = f"improved:{year}:{_cache_ver()}"
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
    key = f"funstats:{year}:{_cache_ver()}"
    data = cache.get(key)
    if data is None:
        data = analytics.funstats(year)
        cache.set(key, data, timeout=60 * 60 * 24)
    return render(
        request,
        _template(request, "web/funstats.html", "web/partials/funstats_body.html"),
        {"year": year, "data": data},
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
