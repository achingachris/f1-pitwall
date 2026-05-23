from django.contrib import admin

from seasons.models import Circuit, Round, Season


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("year", "last_synced")
    ordering = ("-year",)


@admin.register(Circuit)
class CircuitAdmin(admin.ModelAdmin):
    list_display = ("ref", "name", "locality", "country")
    search_fields = ("ref", "name", "country")


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("season", "number", "name", "date", "has_sprint")
    list_filter = ("season", "has_sprint")
    search_fields = ("name",)
