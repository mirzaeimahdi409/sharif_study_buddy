"""Webhook views for Telegram bot."""
import json
import logging
import asyncio
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from telegram import Update

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Telegram webhook updates.
    Receives updates from Telegram and processes them using the bot application.
    """
    from bot.app import get_bot_application, get_bot_event_loop

    try:
        # Get the bot application instance
        application = get_bot_application()
        if application is None:
            logger.error("Bot application not initialized")
            return HttpResponseBadRequest("Bot not ready")

        # Parse the JSON body
        data = json.loads(request.body.decode('utf-8'))

        # Create Update object
        update = Update.de_json(data=data, bot=application.bot)

        # Get the bot's event loop
        bot_loop = get_bot_event_loop()
        if bot_loop is None or not bot_loop.is_running():
            logger.error("Bot event loop not running")
            return HttpResponse(status=200)  # Return 200 to avoid retries

        # Process update in the bot's event loop (thread-safe)
        asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            bot_loop
        )

        logger.debug(f"Update {update.update_id} queued for processing")
        return HttpResponse(status=200)

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook request")
        return HttpResponseBadRequest("Invalid JSON")
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return HttpResponse(status=200)  # Return 200 to avoid retries


def bot_health_check(request: HttpRequest) -> HttpResponse:
    """Health check endpoint."""
    from bot.app import get_bot_application, get_bot_event_loop

    app = get_bot_application()
    loop = get_bot_event_loop()

    if app and loop and loop.is_running():
        return HttpResponse("OK", status=200)
    return HttpResponse("NOT READY", status=503)


def prometheus_metrics(request: HttpRequest) -> HttpResponse:
    """
    Prometheus metrics endpoint.
    Exposes all metrics in Prometheus format.
    """
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from asgiref.sync import sync_to_async
    from core.models import ChatSession, UserProfile
    from core.services import metrics as metrics_module
    
    # Update gauge metrics (active users, total users)
    try:
        from django.db import connection
        # Get active users count (users with active sessions)
        active_sessions = ChatSession.objects.filter(is_active=True).values('user_profile_id').distinct()
        active_users_count = active_sessions.count()
        metrics_module.active_users_total.set(active_users_count)
        
        # Get total users count
        total_users_count = UserProfile.objects.count()
        metrics_module.total_users_total.set(total_users_count)
    except Exception as e:
        logger.warning(f"Failed to update user metrics: {e}")
    
    # Generate Prometheus metrics output
    output = generate_latest()
    return HttpResponse(output, content_type=CONTENT_TYPE_LATEST)
