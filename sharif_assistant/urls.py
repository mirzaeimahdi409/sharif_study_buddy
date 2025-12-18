"""
URL configuration for sharif_assistant project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.conf import settings
from decouple import config

# Import webhook view
from bot.views import telegram_webhook

# Get webhook path from config (optional)


def get_webhook_path():
    """Get webhook path prefix from settings or env."""
    path = getattr(settings, "WEBHOOK_PATH", None) or config(
        "WEBHOOK_PATH", default="/webhook")
    # Ensure path starts with / and doesn't end with /
    if path and not path.startswith("/"):
        path = "/" + path
    if path.endswith("/"):
        path = path.rstrip("/")
    return path


# Build URL patterns
urlpatterns = [
    path("admin/", admin.site.urls),
]

# Add webhook endpoint - use fixed path (no token in URL for better security)
webhook_path = get_webhook_path()
if webhook_path:
    # Remove leading slash for Django path() function
    path_pattern = webhook_path.lstrip("/")
    urlpatterns.append(
        path(f"{path_pattern}/", telegram_webhook, name="telegram_webhook")
    )
else:
    # Fallback: webhook at root path
    urlpatterns.append(
        path("", telegram_webhook, name="telegram_webhook")
    )
