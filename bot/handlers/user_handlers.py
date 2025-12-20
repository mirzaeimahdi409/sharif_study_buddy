"""Handlers for regular user interactions."""
import logging
import time
import base64
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from core.models import ChatSession
from core.config import ChatConfig
from core.services.langgraph_pipeline import run_graph
from bot.utils import get_profile_and_session, format_answer_markdown_to_html
from bot.constants import WELCOME, HELP_TEXT
from bot.keyboards import feedback_keyboard
from core.services import metrics

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    # Track command
    metrics.commands_total.labels(command='start').inc()

    session = await get_profile_and_session(update)

    if update.message:
        await update.message.reply_text(WELCOME, parse_mode="HTML")
        metrics.messages_sent_total.labels(message_type='text').inc()


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    metrics.commands_total.labels(command='help').inc()
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML")
        metrics.messages_sent_total.labels(message_type='text').inc()


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /reset command - reset chat session."""
    if not update.message:
        return ConversationHandler.END

    # Track reset command
    metrics.reset_commands_total.inc()
    metrics.commands_total.labels(command='reset').inc()

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

    # Track session creation
    metrics.user_sessions_total.inc()

    logger.info(
        "User %s reset chat session. New session id=%s",
        update.effective_user.id if update.effective_user else "unknown",
        new_session.id,
    )

    await update.message.reply_text(
        "✅ گفتگوی جدید شروع شد. لطفاً سؤال خود را بپرسید.", parse_mode="HTML"
    )

    metrics.messages_sent_total.labels(message_type='text').inc()

    # Return END to exit any active conversation
    return ConversationHandler.END


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages and photos from users."""
    if not update.message:
        return

    # Determine message type and extract content
    image_data = None
    user_text = ""
    
    if update.message.photo:
        # Handle photo message
        metrics.messages_received_total.labels(message_type='photo').inc()
        
        # Get the highest resolution photo
        photo = update.message.photo[-1]
        try:
            # Download photo
            file = await context.bot.get_file(photo.file_id)
            byte_array = await file.download_as_bytearray()
            
            # Convert to base64
            image_data = base64.b64encode(byte_array).decode('utf-8')
            image_data = f"data:image/jpeg;base64,{image_data}"
            
            # Get caption if available
            user_text = update.message.caption or ""
            
        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            await update.message.reply_text("❌ خطا در پردازش تصویر.")
            return
    else:
        # Handle regular text message
        metrics.messages_received_total.labels(message_type='text').inc()
        user_text = update.message.text or ""

    session = await get_profile_and_session(update)
    user_id = update.effective_user.id if update.effective_user else "unknown"

    logger.info(
        "Received message from user %s (session %s): %s %s",
        user_id,
        session.id,
        (user_text[:100] + "...") if len(user_text) > 100 else user_text,
        "(with image)" if image_data else ""
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
        answer, debug, assistant_msg = await run_graph(session, user_text, image_data=image_data)
        elapsed_time = time.time() - start_time

        # Track message processing duration
        metrics.message_processing_duration_seconds.observe(elapsed_time)

        logger.info(
            "Generated answer for user %s (session %s) in %.2fs. Answer length: %s chars. RAG results: %s",
            user_id,
            session.id,
            elapsed_time,
            len(answer),
            debug.get("rag", {}).get("retrieved_count", 0),
        )
        formatted = format_answer_markdown_to_html(answer)
        
        reply_markup = None
        if ChatConfig.is_feedback_enabled() and assistant_msg:
            reply_markup = feedback_keyboard(assistant_msg.id)
            
        await update.message.reply_text(formatted, parse_mode="HTML", reply_markup=reply_markup)

        # Track sent message
        metrics.messages_sent_total.labels(message_type='text').inc()
    except Exception as e:
        logger.exception(
            "Pipeline error for user %s (session %s): %s", user_id, session.id, e)

        # Track error
        metrics.errors_total.labels(error_type=type(
            e).__name__, component='text_message_handler').inc()
        metrics.pipeline_errors_total.labels(error_type='general_error').inc()

        await update.message.reply_text(
            "متاسفانه خطایی در پردازش پیام شما رخ داد. لطفاً کمی بعد دوباره تلاش کنید."
        )

        # Track error message sent
        metrics.messages_sent_total.labels(message_type='error').inc()
