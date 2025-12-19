"""Handlers for regular user interactions."""
import logging
from bot.metrics import messages_received, commands_processed, errors_total, messages_sent_total
import time
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from core.models import ChatSession
from core.services.langgraph_pipeline import run_graph
from bot.utils import get_profile_and_session, format_answer_markdown_to_html
from bot.constants import WELCOME, HELP_TEXT

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    commands_processed.labels(command='start').inc()
    await get_profile_and_session(update)
    if update.message:
        await update.message.reply_text(WELCOME, parse_mode="HTML")
        messages_sent_total.inc()


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    commands_processed.labels(command='help').inc()
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML")
        messages_sent_total.inc()


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /reset command - reset chat session."""
    commands_processed.labels(command='reset').inc()
    if not update.message:
        return ConversationHandler.END

    # Clear any conversation state
    if context.user_data:
        context.user_data.clear()

    session = await get_profile_and_session(update)
    # Deactivate current session
    from asgiref.sync import sync_to_async
    from core.models import ChatSession
    await sync_to_async(ChatSession.objects.filter(id=session.id).update)(is_active=False)
    # Create new session
    new_session = ChatSession(
        user_profile_id=session.user_profile_id,
        is_active=True,
    )
    await sync_to_async(new_session.save)()

    logger.info(
        "User %s reset chat session. New session id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        new_session.id,
    )

    await update.message.reply_text(
        "✅ گفتگوی جدید شروع شد. لطفاً سؤال خود را بپرسید.", parse_mode="HTML"
    )
    messages_sent_total.inc()

    # Return END to exit any active conversation
    return ConversationHandler.END


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages from users."""
    messages_received.inc()
    if not update.message:
        return
    session = await get_profile_and_session(update)
    user_text = update.message.text or ""
    user_id = update.effective_user.id if update.effective_user else "unknown"

    logger.info(
        "Received message from user %s (session %s): %s",
        user_id,
        session.id,
        (user_text[:100] + "...") if len(user_text) > 100 else user_text,
    )
    # Show "typing..." status in Telegram while we process the message
    if update.effective_chat:
        try:
            await update.effective_chat.send_action(action=ChatAction.TYPING)
        except Exception:
            # Typing indicator failure should not break the main flow
            logger.debug("Failed to send typing action", exc_info=True)

    try:
        start_time = time.time()
        answer, debug = await run_graph(session, user_text)
        elapsed_time = time.time() - start_time
        logger.info(
            "Generated answer for user %s (session %s) in %.2fs. Answer length: %s chars. RAG results: %s",
            user_id,
            session.id,
            elapsed_time,
            len(answer),
            debug.get("rag", {}).get("retrieved_count", 0),
        )
        formatted = format_answer_markdown_to_html(answer)
        await update.message.reply_text(formatted, parse_mode="HTML")
        messages_sent_total.inc()
    except Exception as e:
        errors_total.labels(handler='text_message').inc()
        logger.exception(
            "Pipeline error for user %s (session %s): %s", user_id, session.id, e)
        await update.message.reply_text(
            "متاسفانه خطایی در پردازش پیام شما رخ داد. لطفاً کمی بعد دوباره تلاش کنید."
        )
        messages_sent_total.inc()
