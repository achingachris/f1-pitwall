from django.urls import path

from bot import views

app_name = "bot"

urlpatterns = [
    path("telegram/webhook/<str:secret>/", views.telegram_webhook, name="webhook"),
]
