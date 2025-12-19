"""URL configuration for sharif_assistant project."""
from django.contrib import admin
from django.urls import path, include
from decouple import config

from bot.views import telegram_webhook, bot_health_check

# Get webhook path from config
webhook_path = config("WEBHOOK_PATH", default="webhook").strip("/")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", bot_health_check, name="bot_health_check"),
    path(f"{webhook_path}/", telegram_webhook, name="telegram_webhook"),
    path('metrics/', include('django_prometheus.urls')),
]
