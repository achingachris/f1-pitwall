from django.urls import path

from web import views

app_name = "web"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("<int:year>/", views.season, name="season"),
    path("<int:year>/r/<int:number>/", views.round_detail, name="round"),
    path("<int:year>/standings/drivers/", views.driver_standings, name="driver_standings"),
    path("<int:year>/standings/teams/", views.team_standings, name="team_standings"),
    path("<int:year>/contenders/drivers/", views.driver_contenders, name="driver_contenders"),
    path("<int:year>/contenders/teams/", views.team_contenders, name="team_contenders"),
    path("<int:year>/most-improved/", views.most_improved, name="most_improved"),
    path("<int:year>/funstats/", views.funstats, name="funstats"),
    path("modal/driver/<str:ref>/", views.driver_modal, name="driver_modal"),
    path("modal/team/<str:ref>/", views.team_modal, name="team_modal"),
    path("modal/close/", views.modal_close, name="modal_close"),
]
