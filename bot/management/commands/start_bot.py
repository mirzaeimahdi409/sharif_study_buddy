import os
import asyncio

from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig
from core.config import TelegramConfig
from core.logging_config import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO", use_colors=True)
logger = get_logger(__name__)


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
                asyncio.run(bot.run_webhook())

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
