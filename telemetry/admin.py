from django.contrib import admin

from telemetry.models import Lap, Session, SessionStat, Stint


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("round", "kind", "last_synced")
    list_filter = ("kind", "round__season__year")
    search_fields = ("round__name",)


@admin.register(SessionStat)
class SessionStatAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "driver",
        "constructor",
        "fastest_lap_seconds",
        "top_speed_kmh",
        "laps_completed",
    )
    list_filter = ("session__kind", "session__round__season__year")
    search_fields = ("driver__family_name", "driver__code")
    autocomplete_fields = ("session", "driver", "constructor")


@admin.register(Lap)
class LapAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "driver",
        "number",
        "lap_time_seconds",
        "compound",
        "stint_number",
        "position",
        "is_personal_best",
        "is_deleted",
    )
    list_filter = (
        "session__kind",
        "session__round__season__year",
        "compound",
        "is_personal_best",
        "is_deleted",
    )
    search_fields = ("driver__family_name", "driver__code")


@admin.register(Stint)
class StintAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "driver",
        "number",
        "compound",
        "lap_start",
        "lap_end",
        "laps_count",
        "compound_age_at_start",
    )
    list_filter = ("session__kind", "session__round__season__year", "compound")
    search_fields = ("driver__family_name", "driver__code")
