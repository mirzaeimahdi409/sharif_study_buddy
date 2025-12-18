"""Webhook views for Telegram bot."""
import json
import logging
import asyncio
import hmac
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from decouple import config

from bot.app import get_bot_application

logger = logging.getLogger(__name__)


def verify_webhook_secret(request: HttpRequest) -> bool:
    """
    Verify webhook secret token from X-Telegram-Bot-Api-Secret-Token header.
    Returns True if secret token is valid or not configured, False otherwise.
    """
    secret_token = getattr(settings, "WEBHOOK_SECRET_TOKEN", None) or config(
        "WEBHOOK_SECRET_TOKEN", default=None
    )

    # If no secret token is configured, skip verification (less secure but works)
    if not secret_token:
        return True

    # Get secret token from header
    received_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")

    # Use constant-time comparison to prevent timing attacks
    if not received_token:
        logger.warning("Webhook request missing secret token header")
        return False

    # Compare tokens using constant-time comparison
    try:
        return hmac.compare_digest(received_token, secret_token)
    except Exception as e:
        logger.error(f"Error verifying secret token: {e}")
        return False


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Telegram webhook updates.
    This view receives updates from Telegram and puts them into the bot's update queue.
    """
    try:
        logger.debug("Received webhook request")
        
        # Verify secret token if configured
        if not verify_webhook_secret(request):
            logger.warning("Invalid webhook secret token")
            return HttpResponseForbidden("Invalid secret token")

        # Get the bot application instance
        from bot.app import is_bot_initialized
        application = get_bot_application()

        if application is None:
            logger.error(
                "Bot application not initialized - application instance is None")
            return HttpResponseBadRequest("Bot application not initialized")

        if not is_bot_initialized():
            logger.warning(
                "Bot application instance exists but not fully initialized yet. Waiting...")
            # Wait a bit for initialization (max 5 seconds)
            import time
            for i in range(50):  # 50 * 0.1 = 5 seconds max wait
                time.sleep(0.1)
                if is_bot_initialized():
                    logger.info(f"Bot application is now initialized after {i * 0.1:.1f}s")
                    break
            else:
                logger.error("Bot application initialization timeout after 5 seconds")
                # Return 200 to avoid Telegram retries, but log the error
                # The update will be lost, but at least we won't spam Telegram
                if not is_bot_initialized():
                    logger.error("Bot still not initialized after timeout - update will be lost")
                    return HttpResponse(status=200)  # Return 200 to stop Telegram retries

        # Parse the JSON body
        body = request.body.decode('utf-8')
        data = json.loads(body)

        # Create Update object
        from telegram import Update
        update = Update.de_json(data=data, bot=application.bot)

        # Put update in queue (async operation)
        # Use the bot's event loop if available, otherwise try to schedule in current loop
        from bot.app import get_bot_event_loop
        bot_loop = get_bot_event_loop()

        if bot_loop is not None and bot_loop.is_running():
            # Schedule the coroutine in the bot's event loop (thread-safe)
            future = asyncio.run_coroutine_threadsafe(
                application.update_queue.put(update),
                bot_loop
            )
            # Don't wait for completion to avoid blocking the request
            # The future will complete asynchronously
        else:
            # Fallback: try to use current event loop or create a new one
            try:
                loop = asyncio.get_running_loop()
                # If we have a running loop, schedule the coroutine
                asyncio.create_task(application.update_queue.put(update))
            except RuntimeError:
                # No running loop, create one and run
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        application.update_queue.put(update))
                finally:
                    loop.close()

        logger.info(f"Successfully queued update: {update.update_id}")
        return HttpResponse(status=200)

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook request: {e}")
        return HttpResponseBadRequest("Invalid JSON")
    except Exception as e:
        logger.exception(f"Error processing webhook update: {e}", exc_info=True)
        # Return 200 to Telegram even on error to avoid retries
        # Telegram will retry if we return error status
        return HttpResponse(status=200)


def bot_health_check(request: HttpRequest) -> HttpResponse:
    """
    Health check endpoint to verify bot application status.
    """
    from bot.app import get_bot_application, is_bot_initialized, get_bot_event_loop
    
    application = get_bot_application()
    initialized = is_bot_initialized()
    event_loop = get_bot_event_loop()
    
    status = {
        "application_exists": application is not None,
        "initialized": initialized,
        "event_loop_exists": event_loop is not None,
        "event_loop_running": event_loop.is_running() if event_loop else False,
    }
    
    if all([status["application_exists"], status["initialized"], status["event_loop_running"]]):
        return HttpResponse(f"OK: {status}", status=200, content_type="text/plain")
    else:
        return HttpResponse(f"NOT READY: {status}", status=503, content_type="text/plain")
