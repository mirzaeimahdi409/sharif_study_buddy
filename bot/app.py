"""Main Telegram bot application."""
import asyncio
import logging
from dataclasses import dataclass
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.constants import (
    ADMIN_MAIN,
    ADMIN_NEW_DOC_TITLE,
    ADMIN_NEW_DOC_CONTENT,
    ADMIN_NEW_DOC_SOURCE,
    ADMIN_NEW_URL_DOC_URL,
    ADMIN_NEW_URL_DOC_TITLE,
    ADMIN_LIST_DOCS,
    ADMIN_CHANNELS_ADD_USERNAME,
    ADMIN_CHANNELS_REMOVE_USERNAME,
    ADMIN_CHANNELS_ADD_MESSAGE_COUNT,
    ADMIN_BROADCAST_MENU,
    ADMIN_BROADCAST_FILTER_INPUT,
    ADMIN_BROADCAST_MESSAGE_INPUT,
    ADMIN_BROADCAST_CONFIRM,
)
from bot.handlers.admin_handlers import (
    admin_entry_handler,
    admin_main_callback_handler,
    admin_new_doc_title_handler,
    admin_new_doc_content_handler,
    admin_new_doc_source_handler,
    admin_new_url_doc_url_handler,
    admin_new_url_doc_title_handler,
    admin_channels_add_username_handler,
    admin_channels_remove_username_handler,
    admin_channels_add_message_count_handler,
    admin_cancel_handler,
    admin_broadcast_menu_handler,
    admin_broadcast_filter_handler,
    admin_broadcast_message_handler,
    admin_broadcast_confirm_handler,
)
from bot.handlers.user_handlers import (
    start_handler,
    help_handler,
    reset_handler,
    text_message_handler,
)
from bot.handlers.callback_handlers import debug_callback_handler, feedback_callback_handler

logger = logging.getLogger(__name__)

# Global state for webhook access
_bot_application: Application | None = None
_bot_event_loop: asyncio.AbstractEventLoop | None = None


def get_bot_application() -> Application | None:
    """Get the global bot application instance."""
    return _bot_application


def get_bot_event_loop() -> asyncio.AbstractEventLoop | None:
    """Get the global bot event loop."""
    return _bot_event_loop


@dataclass(frozen=True)
class SharifBotConfig:
    """Configuration for SharifBot."""
    token: str
    webhook_url: str | None = None
    webhook_secret_token: str | None = None


class SharifBot:
    """Main Telegram bot class."""

    def __init__(self, config: SharifBotConfig) -> None:
        """Initialize the bot with configuration."""
        global _bot_application
        self.config = config
        # For webhook mode, disable the internal updater
        builder = Application.builder().token(config.token)
        if config.webhook_url:
            builder = builder.updater(None)
        self.application: Application = builder.build()
        _bot_application = self.application

    def setup_handlers(self) -> None:
        """Set up all bot handlers."""
        # Admin conversation handler
        admin_conv = ConversationHandler(
            entry_points=[CommandHandler("admin", admin_entry_handler)],
            states={
                ADMIN_MAIN: [
                    CallbackQueryHandler(
                        admin_main_callback_handler, pattern=r"^admin:")
                ],
                ADMIN_LIST_DOCS: [
                    CallbackQueryHandler(
                        admin_main_callback_handler, pattern=r"^admin:")
                ],
                ADMIN_NEW_DOC_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_new_doc_title_handler)
                ],
                ADMIN_NEW_DOC_CONTENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_new_doc_content_handler)
                ],
                ADMIN_NEW_DOC_SOURCE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_new_doc_source_handler)
                ],
                ADMIN_NEW_URL_DOC_URL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_new_url_doc_url_handler)
                ],
                ADMIN_NEW_URL_DOC_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_new_url_doc_title_handler)
                ],
                ADMIN_CHANNELS_ADD_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_channels_add_username_handler)
                ],
                ADMIN_CHANNELS_REMOVE_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_channels_remove_username_handler)
                ],
                ADMIN_CHANNELS_ADD_MESSAGE_COUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_channels_add_message_count_handler)
                ],
                ADMIN_BROADCAST_MENU: [
                    CallbackQueryHandler(
                        admin_broadcast_menu_handler, pattern=r"^admin:broadcast:")
                ],
                ADMIN_BROADCAST_FILTER_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_broadcast_filter_handler)
                ],
                ADMIN_BROADCAST_MESSAGE_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   admin_broadcast_message_handler)
                ],
                ADMIN_BROADCAST_CONFIRM: [
                    CallbackQueryHandler(
                        admin_broadcast_confirm_handler, pattern=r"^admin:broadcast:")
                ],
            },
            fallbacks=[
                CommandHandler("cancel", admin_cancel_handler),
                CommandHandler("reset", reset_handler),
            ],
            name="admin_conversation",
            persistent=False,
        )

        # Add handlers
        self.application.add_handler(CommandHandler("reset", reset_handler))
        self.application.add_handler(CommandHandler("start", start_handler))
        self.application.add_handler(CommandHandler("help", help_handler))
        self.application.add_handler(admin_conv)
        self.application.add_handler(
            CallbackQueryHandler(feedback_callback_handler, pattern="^fb:")
        )
        self.application.add_handler(
            CallbackQueryHandler(debug_callback_handler))
        self.application.add_handler(
            MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
                           text_message_handler)
        )

    def run_polling(self) -> None:
        """Run the bot in polling mode."""
        self.setup_handlers()
        logger.info("Starting bot polling...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def run_webhook(self) -> None:
        """Run the bot in webhook mode."""
        global _bot_event_loop

        self.setup_handlers()

        # Initialize and start the application
        await self.application.initialize()
        await self.application.start()

        # Store event loop for webhook views
        _bot_event_loop = asyncio.get_running_loop()

        # Set webhook URL with Telegram
        if self.config.webhook_url:
            webhook_params = {
                "url": self.config.webhook_url,
                "allowed_updates": Update.ALL_TYPES,
            }
            if self.config.webhook_secret_token:
                webhook_params["secret_token"] = self.config.webhook_secret_token

            await self.application.bot.set_webhook(**webhook_params)

            # Verify webhook
            info = await self.application.bot.get_webhook_info()
            logger.info(
                f"Webhook set: {info.url} (pending: {info.pending_update_count})")

        logger.info("Bot application started and ready")

    async def stop(self) -> None:
        """Stop the bot application."""
        try:
            await self.application.stop()
            await self.application.shutdown()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
