from django.contrib import admin
from django.urls import include, path

handler400 = "web.views.bad_request"
handler403 = "web.views.permission_denied"
handler404 = "web.views.page_not_found"
handler500 = "web.views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("bot.urls")),
    path("", include("web.urls")),
]
