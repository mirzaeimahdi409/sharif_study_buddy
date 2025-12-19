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


@csrf_exempt
def prometheus_metrics(request: HttpRequest) -> HttpResponse:
    """
    Prometheus metrics endpoint.
    Exposes all metrics in Prometheus format.
    """
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    except ImportError:
        logger.error("prometheus_client not installed")
        return HttpResponseBadRequest("Prometheus client not available", status=503)

    # Only allow GET requests (Prometheus uses GET)
    if request.method != 'GET':
        return HttpResponseBadRequest("Only GET method is allowed")

    # Update gauge metrics (active users, total users)
    try:
        from core.models import ChatSession, UserProfile
        from core.services import metrics as metrics_module

        # Get active users count (users with active sessions)
        active_sessions = ChatSession.objects.filter(
            is_active=True).values('user_profile_id').distinct()
        active_users_count = active_sessions.count()
        metrics_module.active_users_total.set(active_users_count)

        # Get total users count
        total_users_count = UserProfile.objects.count()
        metrics_module.total_users_total.set(total_users_count)
    except Exception as e:
        logger.warning(f"Failed to update user metrics: {e}", exc_info=True)

    # Generate Prometheus metrics output
    try:
        output = generate_latest()
        # generate_latest() returns bytes
        if not isinstance(output, bytes):
            output = str(output).encode('utf-8')

        response = HttpResponse(output, content_type=CONTENT_TYPE_LATEST)
        return response
    except Exception as e:
        logger.error(f"Error generating metrics: {e}", exc_info=True)
        return HttpResponseBadRequest(f"Error generating metrics: {str(e)}")
