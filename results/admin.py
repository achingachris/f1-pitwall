from django.contrib import admin

from results.models import Qualifying, Result, Standing


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        "round",
        "session",
        "position_text",
        "driver",
        "constructor",
        "points",
        "status",
    )
    list_filter = ("session", "round__season")
    search_fields = ("driver__family_name", "constructor__name")
    autocomplete_fields = ("round", "driver", "constructor")


@admin.register(Qualifying)
class QualifyingAdmin(admin.ModelAdmin):
    list_display = ("round", "position", "driver", "constructor", "q1", "q2", "q3")
    list_filter = ("round__season",)
    search_fields = ("driver__family_name",)
    autocomplete_fields = ("round", "driver", "constructor")


@admin.register(Standing)
class StandingAdmin(admin.ModelAdmin):
    list_display = ("round", "kind", "position", "driver", "constructor", "points", "wins")
    list_filter = ("kind", "round__season")
    autocomplete_fields = ("round", "driver", "constructor")
