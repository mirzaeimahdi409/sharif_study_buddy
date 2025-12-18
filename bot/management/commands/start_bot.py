import os
import asyncio
import signal
from django.core.management.base import BaseCommand

from bot.app import SharifBot, SharifBotConfig
from core.config import TelegramConfig
from core.logging_config import setup_logging, get_logger

setup_logging(level="INFO", use_colors=True)
logger = get_logger(__name__)

# Global for cleanup
_bot: SharifBot | None = None
_shutdown = asyncio.Event()


async def run_webhook_bot(bot: SharifBot) -> None:
    """Run the bot in webhook mode."""
    try:
        await bot.run_webhook()
        logger.info("Bot is running. Waiting for shutdown...")
        await _shutdown.wait()
    finally:
        await bot.stop()
        logger.info("Bot stopped")


def handle_signal(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}")
    _shutdown.set()


class Command(BaseCommand):
    help = 'Starts the Telegram bot in polling or webhook mode'

    def handle(self, *args, **options):
        global _bot

        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))

        try:
            token = TelegramConfig.get_bot_token()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Token not found: {e}'))
            return

        run_mode = os.getenv("DJANGO_ENV", "development")

        # Register signal handlers
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            if run_mode == "production":
                # Webhook Mode
                webhook_domain = TelegramConfig.get_webhook_domain()
                if not webhook_domain:
                    self.stdout.write(self.style.ERROR(
                        '❌ WEBHOOK_DOMAIN not set'))
                    return

                webhook_path = TelegramConfig.get_webhook_path()
                secret_token = TelegramConfig.get_webhook_secret_token()
                webhook_url = f"https://{webhook_domain}{webhook_path}/"

                if not secret_token:
                    logger.warning("No WEBHOOK_SECRET_TOKEN configured")

                _bot = SharifBot(SharifBotConfig(
                    token=token,
                    webhook_url=webhook_url,
                    webhook_secret_token=secret_token
                ))

                self.stdout.write(self.style.SUCCESS(
                    f'✅ Webhook mode: {webhook_url}'))

                # Run in event loop
                asyncio.run(run_webhook_bot(_bot))

            else:
                # Polling Mode
                _bot = SharifBot(SharifBotConfig(token=token))
                self.stdout.write(self.style.SUCCESS(
                    '✅ Polling mode. Press CTRL-C to stop.'))
                _bot.run_polling()

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n⚠️ Stopped by user.'))
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
            self.stdout.write(self.style.ERROR(f'❌ Fatal error: {e}'))
        finally:
            self.stdout.write(self.style.SUCCESS('Bot stopped.'))
