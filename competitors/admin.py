from django.contrib import admin

from competitors.models import Constructor, Driver


@admin.register(Constructor)
class ConstructorAdmin(admin.ModelAdmin):
    list_display = ("ref", "name", "nationality")
    search_fields = ("ref", "name")


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("code", "given_name", "family_name", "nationality")
    search_fields = ("code", "given_name", "family_name")
