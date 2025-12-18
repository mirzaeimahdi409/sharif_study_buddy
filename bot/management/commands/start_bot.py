"""
Management command to start the Telegram bot.

In production (webhook mode): Bot starts automatically with Django via BotConfig.ready()
In development (polling mode): Use this command to start the bot manually.
"""
import os
import signal
from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig
from core.config import TelegramConfig
from core.logging_config import setup_logging, get_logger

setup_logging(level="INFO", use_colors=True)
logger = get_logger(__name__)


class Command(BaseCommand):
    help = 'Starts the Telegram bot (for development/polling mode)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))

        try:
            token = TelegramConfig.get_bot_token()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Token not found: {e}'))
            return

        run_mode = os.getenv("DJANGO_ENV", "development")

        if run_mode == "production":
            self.stdout.write(self.style.WARNING(
                '⚠️ In production mode, bot starts automatically with Django.\n'
                'This command is not needed. Just start Django server.'
            ))
            return

        # Polling Mode (development)
        try:
            bot = SharifBot(SharifBotConfig(token=token))
            self.stdout.write(self.style.SUCCESS(
                '✅ Polling mode. Press CTRL-C to stop.'))
            bot.run_polling()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n⚠️ Stopped by user.'))
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
            self.stdout.write(self.style.ERROR(f'❌ Fatal error: {e}'))
        finally:
            self.stdout.write(self.style.SUCCESS('Bot stopped.'))
