import os
import asyncio

from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig
from core.config import TelegramConfig
from core.logging_config import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO", use_colors=True)
logger = get_logger(__name__)


def run_async(coro):
    """
    Run an async coroutine, handling both cases where an event loop
    is already running or not.
    """
    try:
        # Check if there's already a running event loop
        loop = asyncio.get_running_loop()
        # If we get here, there's a running loop
        # We need to run in a separate thread with its own event loop
        import threading

        result = None
        exception = None

        def run_in_thread():
            nonlocal result, exception
            # Create a new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result = new_loop.run_until_complete(coro)
            except Exception as e:
                exception = e
            finally:
                new_loop.close()

        thread = threading.Thread(target=run_in_thread, daemon=False)
        thread.start()
        thread.join()

        if exception:
            raise exception
        return result
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
        asyncio.run(coro)


class Command(BaseCommand):
    help = 'Starts the Telegram bot in polling or webhook mode'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        try:
            token = TelegramConfig.get_bot_token()
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'❌ Telegram bot token not found: {e}'))
            logger.error("TELEGRAM_BOT_TOKEN not configured: %s", e)
            return

        run_mode = os.getenv("DJANGO_ENV", "development")

        try:
            if run_mode == "production":
                # --- Webhook Mode ---
                webhook_domain = TelegramConfig.get_webhook_domain()
                if not webhook_domain:
                    self.stdout.write(self.style.ERROR(
                        '❌ WEBHOOK_DOMAIN not set in production environment.'))
                    logger.error(
                        "WEBHOOK_DOMAIN not configured for production")
                    return

                webhook_url = f"https://{webhook_domain}/{token}"
                bot_config = SharifBotConfig(
                    token=token, webhook_url=webhook_url)
                bot = SharifBot(bot_config)

                logger.info(
                    "Telegram bot application initialized for webhook mode.")
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Bot is starting in webhook mode. URL: {webhook_url}'))

                # Run the async webhook setup
                run_async(bot.run_webhook())

            else:
                # --- Polling Mode ---
                bot_config = SharifBotConfig(token=token)
                bot = SharifBot(bot_config)

                logger.info(
                    "Telegram bot application initialized for polling mode.")
                self.stdout.write(self.style.SUCCESS(
                    '✅ Bot is running in polling mode. Press CTRL-C to stop.'))

                # This is a blocking call
                bot.run_polling()

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (KeyboardInterrupt)")
            self.stdout.write(self.style.WARNING('\n⚠️  Bot stopped by user.'))
        except Exception as e:
            logger.exception(f"Fatal error in bot: {e}", exc_info=True)
            self.stdout.write(self.style.ERROR(
                f'❌ Fatal error: {e}'))
            raise
        finally:
            logger.info("Bot shutdown complete")
            self.stdout.write(self.style.SUCCESS('Bot stopped.'))
