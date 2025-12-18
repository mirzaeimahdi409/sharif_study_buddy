"""Webhook views for Telegram bot."""
import json
import logging
import asyncio
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot.app import get_bot_application

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Telegram webhook updates.
    This view receives updates from Telegram and puts them into the bot's update queue.
    """
    try:
        # Get the bot application instance
        application = get_bot_application()
        if application is None:
            logger.error("Bot application not initialized")
            return HttpResponseBadRequest("Bot application not initialized")

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
                    loop.run_until_complete(application.update_queue.put(update))
                finally:
                    loop.close()

        logger.debug(f"Received update: {update.update_id}")
        return HttpResponse(status=200)

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook request: {e}")
        return HttpResponseBadRequest("Invalid JSON")
    except Exception as e:
        logger.exception(f"Error processing webhook update: {e}")
        return HttpResponseBadRequest(f"Error processing update: {e}")

