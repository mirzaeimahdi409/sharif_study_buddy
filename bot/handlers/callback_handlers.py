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


async def feedback_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle feedback (thumbs up/down) callback queries."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("fb:"):
        return

    # fb:like:ID or fb:dislike:ID
    parts = data.split(":")
    if len(parts) != 3:
        return

    action = parts[1]
    try:
        msg_id = int(parts[2])
    except ValueError:
        logger.error(f"Invalid message ID in feedback: {parts[2]}")
        return

    feedback_value = 1 if action == "like" else -1

    # Update DB
    try:
        from core.models import ChatMessage
        from asgiref.sync import sync_to_async
        
        @sync_to_async
        def update_feedback(mid, val):
            try:
                msg = ChatMessage.objects.get(id=mid)
                msg.feedback = val
                msg.save()
                return msg
            except ChatMessage.DoesNotExist:
                return None

        msg = await update_feedback(msg_id, feedback_value)
        
        if msg:
            # Remove keyboard after feedback
            await query.edit_message_reply_markup(reply_markup=None)
        else:
            logger.warning(f"ChatMessage {msg_id} not found for feedback.")
            
    except Exception as e:
        logger.error(f"Error handling feedback: {e}")
