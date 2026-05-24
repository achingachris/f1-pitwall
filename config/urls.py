from django.contrib import admin
from django.urls import include, path

from web.admin_views import celery_status

handler400 = "web.views.bad_request"
handler403 = "web.views.permission_denied"
handler404 = "web.views.page_not_found"
handler500 = "web.views.server_error"

# Splice the Celery live-status view into the admin URL namespace so it
# inherits admin auth + can link from the admin index. Wrapping in
# admin.site.admin_view() enforces the staff-member check.
_original_get_urls = admin.site.get_urls


def _get_urls():
    return [
        path(
            "celery/status/",
            admin.site.admin_view(celery_status),
            name="celery-status",
        ),
    ] + _original_get_urls()


admin.site.get_urls = _get_urls
# Override the admin index template so we can add a Celery section above the
# default app list. The template extends "admin/index.html" — naming it
# anything but that avoids the self-referential template lookup.
admin.site.index_template = "admin/pitwall_index.html"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("bot.urls")),
    path("", include("web.urls")),
]
