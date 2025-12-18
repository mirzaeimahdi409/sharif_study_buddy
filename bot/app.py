"""Main Telegram bot application."""
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
    admin_cancel_handler,
)
from bot.handlers.user_handlers import (
    start_handler,
    help_handler,
    reset_handler,
    text_message_handler,
)
from bot.handlers.callback_handlers import debug_callback_handler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SharifBotConfig:
    """Configuration for SharifBot."""
    token: str
    webhook_url: str | None = None


class SharifBot:
    """Main Telegram bot class."""

    def __init__(self, config: SharifBotConfig) -> None:
        """Initialize the bot with configuration."""
        self.config = config
        self.application: Application = Application.builder().token(config.token).build()

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
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin_new_doc_title_handler
                    )
                ],
                ADMIN_NEW_DOC_CONTENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin_new_doc_content_handler
                    )
                ],
                ADMIN_NEW_DOC_SOURCE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin_new_doc_source_handler
                    )
                ],
                ADMIN_NEW_URL_DOC_URL: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin_new_url_doc_url_handler
                    )
                ],
                ADMIN_NEW_URL_DOC_TITLE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin_new_url_doc_title_handler
                    )
                ],
                ADMIN_CHANNELS_ADD_USERNAME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_channels_add_username_handler,
                    )
                ],
                ADMIN_CHANNELS_REMOVE_USERNAME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_channels_remove_username_handler,
                    )
                ],
            },
            fallbacks=[
                CommandHandler("cancel", admin_cancel_handler),
                # Allow reset to exit admin conversation
                CommandHandler("reset", reset_handler),
            ],
            name="admin_conversation",
            persistent=False,
        )

        # IMPORTANT: ConversationHandler must be added BEFORE the general MessageHandler
        # Add reset handler FIRST so it can work even if user is in a conversation
        self.application.add_handler(CommandHandler("reset", reset_handler))
        self.application.add_handler(CommandHandler("start", start_handler))
        self.application.add_handler(CommandHandler("help", help_handler))

        self.application.add_handler(admin_conv)
        self.application.add_handler(
            CallbackQueryHandler(debug_callback_handler))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND,
                           text_message_handler)
        )

    def run_polling(self) -> None:
        """Run the bot in polling mode."""
        self.setup_handlers()
        logger.info("Starting bot polling...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def run_webhook(self) -> None:
        """Run the bot in webhook mode."""
        self.setup_handlers()
        if not self.config.webhook_url:
            logger.error("Webhook URL not provided in config.")
            return

        logger.info(f"Starting bot with webhook: {self.config.webhook_url}")
        await self.application.run_webhook(
            listen="0.0.0.0",
            port=8443,
            webhook_url=self.config.webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
