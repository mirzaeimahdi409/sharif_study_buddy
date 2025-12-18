import os
import asyncio
import threading
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class BotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bot"

    def ready(self):
        """Start bot when Django loads (only in production/webhook mode)."""
        # Avoid running twice (Django reloader)
        if os.environ.get('RUN_MAIN') != 'true' and 'runserver' in os.environ.get('DJANGO_COMMAND', ''):
            return

        run_mode = os.getenv("DJANGO_ENV", "development")
        if run_mode != "production":
            logger.info(
                "Development mode - bot will use polling via start_bot command")
            return

        # Start bot in background thread
        thread = threading.Thread(
            target=self._start_bot, daemon=True, name="TelegramBot")
        thread.start()
        logger.info("Bot thread started")

    def _start_bot(self):
        """Initialize and run the bot in a separate thread."""
        from bot.app import SharifBot, SharifBotConfig
        from core.config import TelegramConfig

        try:
            token = TelegramConfig.get_bot_token()
            webhook_domain = TelegramConfig.get_webhook_domain()
            webhook_path = TelegramConfig.get_webhook_path()
            secret_token = TelegramConfig.get_webhook_secret_token()

            if not webhook_domain:
                logger.error("WEBHOOK_DOMAIN not configured")
                return

            webhook_url = f"https://{webhook_domain}{webhook_path}/"

            bot = SharifBot(SharifBotConfig(
                token=token,
                webhook_url=webhook_url,
                webhook_secret_token=secret_token
            ))

            # Run the async bot in this thread's event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                loop.run_until_complete(bot.run_webhook())
                logger.info(f"Bot ready. Webhook: {webhook_url}")
                # Keep the loop running
                loop.run_forever()
            except Exception as e:
                logger.exception(f"Bot error: {e}")
            finally:
                loop.close()

        except Exception as e:
            logger.exception(f"Failed to start bot: {e}")
