import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Starts the Telegram bot'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stdout.write(self.style.ERROR(
                '❌ Telegram bot token not found. Set TELEGRAM_BOT_TOKEN in environment variables.'))
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        try:
            bot = SharifBot(SharifBotConfig(token=token))
            logger.info("Telegram bot application initialized successfully (class-based runner)")
            self.stdout.write(self.style.SUCCESS(
                '✅ Bot is running. Press CTRL-C to stop.'))
            logger.info("Starting bot polling...")

            bot.run()

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
