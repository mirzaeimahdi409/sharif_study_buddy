import os
import asyncio
import signal
import threading
from typing import Optional

from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig
from core.config import TelegramConfig
from core.logging_config import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO", use_colors=True)
logger = get_logger(__name__)

# Global variable to store the bot instance for cleanup
_bot_instance: Optional[SharifBot] = None
_shutdown_event = threading.Event()


def run_async_application(bot: SharifBot) -> None:
    """
    Run the async bot application in a separate event loop.
    This is used for webhook mode where Django handles the HTTP requests.
    """
    async def main():
        try:
            # Initialize and start the application
            await bot.start_application()

            # Set up the webhook URL (after application is started)
            await bot.setup_webhook()

            logger.info("Bot application is running. Waiting for updates...")

            # Keep the application running
            # The application will process updates from the queue
            # We need to keep the event loop running
            try:
                # Wait indefinitely until shutdown
                while not _shutdown_event.is_set():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Application loop cancelled")

        except Exception as e:
            logger.exception(f"Error in async application: {e}", exc_info=True)
            raise
        finally:
            # Cleanup
            try:
                await bot.stop_application()
                await bot.shutdown_application()
            except Exception as e:
                logger.error(f"Error during shutdown: {e}", exc_info=True)

    # Run in a new event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.exception(
            f"Fatal error in async application: {e}", exc_info=True)
        raise
    finally:
        if loop:
            try:
                # Cancel all pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Wait for tasks to complete cancellation
                if pending:
                    loop.run_until_complete(asyncio.gather(
                        *pending, return_exceptions=True))
            except Exception as e:
                logger.error(f"Error cleaning up tasks: {e}", exc_info=True)
            finally:
                loop.close()


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, shutting down...")
    _shutdown_event.set()
    if _bot_instance:
        # Trigger shutdown
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_bot_instance.stop_application())
        except Exception:
            pass


class Command(BaseCommand):
    help = 'Starts the Telegram bot in polling or webhook mode'

    def handle(self, *args, **options):
        global _bot_instance

        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        try:
            token = TelegramConfig.get_bot_token()
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'❌ Telegram bot token not found: {e}'))
            logger.error("TELEGRAM_BOT_TOKEN not configured: %s", e)
            return

        run_mode = os.getenv("DJANGO_ENV", "development")

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            if run_mode == "production":
                # --- Webhook Mode (Custom) ---
                webhook_domain = TelegramConfig.get_webhook_domain()
                if not webhook_domain:
                    self.stdout.write(self.style.ERROR(
                        '❌ WEBHOOK_DOMAIN not set in production environment.'))
                    logger.error(
                        "WEBHOOK_DOMAIN not configured for production")
                    return

                # Get webhook path (defaults to /webhook)
                webhook_path = TelegramConfig.get_webhook_path()
                # Get secret token for webhook security (optional but recommended)
                secret_token = TelegramConfig.get_webhook_secret_token()

                # Build webhook URL (without token in path for better security)
                # Ensure trailing slash to match Django URL pattern
                if webhook_path:
                    webhook_url = f"https://{webhook_domain}{webhook_path}/"
                else:
                    # Root path
                    webhook_url = f"https://{webhook_domain}/"

                if secret_token:
                    logger.info("Using secret token for webhook security")
                else:
                    logger.warning(
                        "No secret token configured. Consider setting WEBHOOK_SECRET_TOKEN for better security.")

                bot_config = SharifBotConfig(
                    token=token,
                    webhook_url=webhook_url,
                    webhook_secret_token=secret_token
                )
                _bot_instance = SharifBot(bot_config)

                logger.info(
                    "Telegram bot application initialized for webhook mode.")
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Bot is starting in webhook mode. URL: {webhook_url}'))
                self.stdout.write(self.style.SUCCESS(
                    '✅ Bot application will run in the background. Django will handle webhook requests.'))

                # Run the async application in a separate thread
                # This allows Django to continue running while the bot processes updates
                thread = threading.Thread(
                    target=run_async_application,
                    args=(_bot_instance,),
                    daemon=True
                )
                thread.start()

                # Wait for the thread (or until interrupted)
                try:
                    thread.join()
                except KeyboardInterrupt:
                    logger.info("Bot stopped by user (KeyboardInterrupt)")
                    self.stdout.write(self.style.WARNING(
                        '\n⚠️  Bot stopped by user.'))
                    _shutdown_event.set()

            else:
                # --- Polling Mode ---
                bot_config = SharifBotConfig(token=token)
                _bot_instance = SharifBot(bot_config)

                logger.info(
                    "Telegram bot application initialized for polling mode.")
                self.stdout.write(self.style.SUCCESS(
                    '✅ Bot is running in polling mode. Press CTRL-C to stop.'))

                # This is a blocking call
                _bot_instance.run_polling()

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (KeyboardInterrupt)")
            self.stdout.write(self.style.WARNING('\n⚠️  Bot stopped by user.'))
        except Exception as e:
            logger.exception(f"Fatal error in bot: {e}", exc_info=True)
            self.stdout.write(self.style.ERROR(
                f'❌ Fatal error: {e}'))
            raise
        finally:
            _shutdown_event.set()
            logger.info("Bot shutdown complete")
            self.stdout.write(self.style.SUCCESS('Bot stopped.'))
