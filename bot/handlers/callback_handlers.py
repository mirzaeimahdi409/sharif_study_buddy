"""Callback query handlers for the Telegram bot."""
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def debug_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Debug callback handler for logging callback queries."""
    query = update.callback_query
    if query and update.effective_user:
        logger.info(
            "DEBUG: Callback query received: %s from user %s",
            query.data,
            update.effective_user.id,
        )
