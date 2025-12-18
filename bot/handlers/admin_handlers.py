"""Admin handlers for the Telegram bot."""
import logging
import time
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from core.models import ChatMessage, ChatSession, KnowledgeDocument, UserProfile
from core.services.rag_client import RAGClient
from core.exceptions import RAGServiceError
from core.tasks import push_document_to_rag, reprocess_document_in_rag
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
from bot.utils import get_admin_ids, escape_markdown_v2
from bot.keyboards import (
    admin_main_keyboard,
    admin_docs_keyboard,
    admin_channels_keyboard,
)

if TYPE_CHECKING:
    from telegram import CallbackQuery

logger = logging.getLogger(__name__)


def is_admin(update: Update) -> bool:
    """Check if the user is an admin."""
    tg_user = update.effective_user
    return bool(tg_user) and str(tg_user.id) in get_admin_ids()


async def admin_entry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /admin command entry."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ شما دسترسی ادمین برای این بات را ندارید.")
        return ConversationHandler.END

    await update.message.reply_text(
        "👑 به پنل ادمین بات خوش آمدید.\n"
        "از دکمه‌های زیر برای مدیریت بات استفاده کنید:",
        reply_markup=admin_main_keyboard(),
    )
    return ADMIN_MAIN


async def admin_main_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin callback queries."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    data = query.data or ""
    try:
        await query.answer()
    except Exception:
        pass

    if data == "admin:exit":
        await query.edit_message_text("خروج از حالت ادمین انجام شد.")
        return ConversationHandler.END

    if data == "admin:docs":
        await query.edit_message_text(
            "📚 مدیریت اسناد دانش:",
            reply_markup=admin_docs_keyboard(),
        )
        return ADMIN_MAIN

    if data == "admin:back_main":
        await query.edit_message_text(
            "👑 پنل ادمین:", reply_markup=admin_main_keyboard()
        )
        return ADMIN_MAIN

    if data == "admin:channels":
        await query.edit_message_text(
            "📡 مدیریت کانال‌ها:",
            reply_markup=admin_channels_keyboard(),
        )
        return ADMIN_MAIN

    if data == "admin:channels:list":
        await _handle_channels_list(query)
        return ADMIN_MAIN

    if data == "admin:channels:add":
        await query.edit_message_text("لطفاً نام کاربری کانال جدید را برای افزودن ارسال کنید:")
        return ADMIN_CHANNELS_ADD_USERNAME

    if data == "admin:channels:remove":
        await query.edit_message_text("لطفاً نام کاربری کانال را برای حذف ارسال کنید:")
        return ADMIN_CHANNELS_REMOVE_USERNAME

    if data == "admin:stats":
        await _handle_stats(query)
        return ADMIN_MAIN

    if data == "admin:push_unindexed":
        await _handle_push_unindexed(query)
        return ADMIN_MAIN

    if data == "admin:reprocess_all":
        await _handle_reprocess_all(query)
        return ADMIN_MAIN

    if data == "admin:create_doc_text":
        await query.edit_message_text("➕ ایجاد سند متنی جدید\nعنوان سند را ارسال کنید:")
        return ADMIN_NEW_DOC_TITLE

    if data == "admin:create_doc_url":
        await query.edit_message_text("➕ ایجاد سند از لینک وب‌سایت\nلینک صفحه وب‌سایت را ارسال کنید:")
        return ADMIN_NEW_URL_DOC_URL

    # Handle list docs pagination: admin:list_docs:0, admin:list_docs:10, etc.
    if data.startswith("admin:list_docs:"):
        try:
            page = int(data.split(":")[-1])
        except (ValueError, IndexError):
            page = 0
        await _show_docs_list(query, page)
        return ADMIN_LIST_DOCS

    # Handle delete doc: admin:delete_doc:123
    if data.startswith("admin:delete_doc:"):
        try:
            doc_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await query.answer("❌ شناسه سند نامعتبر است.", show_alert=True)
            return ADMIN_MAIN
        await _delete_document(query, doc_id)
        return ADMIN_LIST_DOCS

    # Handle confirm delete: admin:confirm_delete:123
    if data.startswith("admin:confirm_delete:"):
        try:
            doc_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await query.answer("❌ شناسه سند نامعتبر است.", show_alert=True)
            return ADMIN_MAIN
        await _confirm_delete_document(query, doc_id)
        return ADMIN_LIST_DOCS

    return ADMIN_MAIN


async def admin_new_doc_title_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin new document title input."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
        return ConversationHandler.END

    title = (update.message.text or "").strip()
    if not title:
        await update.message.reply_text("❗ لطفاً یک عنوان معتبر ارسال کنید.")
        return ADMIN_NEW_DOC_TITLE

    context.user_data["new_doc_title"] = title
    await update.message.reply_text("متن کامل سند را ارسال کنید:")
    return ADMIN_NEW_DOC_CONTENT


async def admin_new_doc_content_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin new document content input."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
        return ConversationHandler.END

    content = (update.message.text or "").strip()
    if not content:
        await update.message.reply_text("❗ لطفاً متن سند را ارسال کنید.")
        return ADMIN_NEW_DOC_CONTENT

    context.user_data["new_doc_content"] = content
    await update.message.reply_text(
        "اگر این سند از یک URL خاص است، لینک را ارسال کنید.\nدر غیر این صورت \"-\" را ارسال کنید:"
    )
    return ADMIN_NEW_DOC_SOURCE


async def admin_new_doc_source_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin new document source input."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
        return ConversationHandler.END

    source_text = (update.message.text or "").strip()
    source_url = None if source_text in {"", "-"} else source_text

    title = context.user_data.get("new_doc_title", "")
    content = context.user_data.get("new_doc_content", "")

    logger.info(
        "Admin creating KnowledgeDocument (text). title=%r source_url=%r",
        title,
        source_url,
    )
    try:
        doc = await sync_to_async(KnowledgeDocument.objects.create)(
            title=title, content=content, source_url=source_url, metadata={}
        )
        logger.info("KnowledgeDocument created successfully id=%s", doc.id)
        try:
            push_document_to_rag.delay(doc.id)
            logger.info("Queued push_document_to_rag for doc id=%s", doc.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue push_document_to_rag for doc id=%s: %s",
                doc.id,
                e,
            )
    except Exception as e:
        logger.exception(
            "Error while creating KnowledgeDocument (text). title=%r source_url=%r: %s",
            title,
            source_url,
            e,
        )
        await update.message.reply_text(
            "❌ خطا در ایجاد سند. جزئیات خطا در لاگ سرور ثبت شد."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ سند جدید ایجاد شد و برای ایندکس در RAG در صف قرار گرفت.\n"
        f"عنوان: {doc.title}"
    )

    context.user_data.pop("new_doc_title", None)
    context.user_data.pop("new_doc_content", None)
    return ConversationHandler.END


async def admin_new_url_doc_url_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin new URL document URL input."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
        return ConversationHandler.END

    url_text = (update.message.text or "").strip()
    if not (url_text.startswith("http://") or url_text.startswith("https://")):
        await update.message.reply_text(
            "❗ لطفاً یک لینک معتبر که با http:// یا https:// شروع می‌شود ارسال کنید."
        )
        return ADMIN_NEW_URL_DOC_URL

    context.user_data["new_doc_source_url"] = url_text
    await update.message.reply_text(
        "عنوان سند را ارسال کنید (یا برای استفاده از خود لینک، «-» را بفرستید):"
    )
    return ADMIN_NEW_URL_DOC_TITLE


async def admin_new_url_doc_title_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin new URL document title input."""
    if not update.message:
        return ConversationHandler.END
    if not is_admin(update):
        await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
        return ConversationHandler.END

    title_text = (update.message.text or "").strip()
    source_url = context.user_data.get("new_doc_source_url", "")
    if not source_url:
        await update.message.reply_text("❗ لینک سند پیدا نشد، لطفاً دوباره تلاش کنید.")
        return ConversationHandler.END

    title = (
        f"سند از وب‌سایت ({source_url})"
        if (not title_text or title_text == "-")
        else title_text
    )

    logger.info(
        "Admin creating KnowledgeDocument (url). title=%r source_url=%r",
        title,
        source_url,
    )
    try:
        doc = await sync_to_async(KnowledgeDocument.objects.create)(
            title=title, content="", source_url=source_url, metadata={}
        )
        logger.info("KnowledgeDocument (url) created successfully id=%s", doc.id)
        try:
            push_document_to_rag.delay(doc.id)
            logger.info("Queued push_document_to_rag for doc id=%s", doc.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue push_document_to_rag for url doc id=%s: %s",
                doc.id,
                e,
            )
    except Exception as e:
        logger.exception(
            "Error while creating KnowledgeDocument (url). title=%r source_url=%r: %s",
            title,
            source_url,
            e,
        )
        await update.message.reply_text(
            "❌ خطا در ایجاد سند از لینک وب‌سایت. جزئیات خطا در لاگ سرور ثبت شد."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ سند جدید از لینک وب‌سایت ایجاد شد و برای ایندکس در RAG در صف قرار گرفت.\n"
        f"عنوان: {doc.title}\n"
        f"لینک: {source_url}"
    )
    context.user_data.pop("new_doc_source_url", None)
    return ConversationHandler.END


async def admin_channels_add_username_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin channel add username input."""
    if not update.message or not update.message.text:
        return ADMIN_CHANNELS_ADD_USERNAME

    channel_username = update.message.text.lstrip("@").strip()
    if not channel_username:
        await update.message.reply_text("نام کاربری نامعتبر است. لطفاً دوباره تلاش کنید.")
        return ADMIN_CHANNELS_ADD_USERNAME

    from monitoring.models import MonitoredChannel

    _, created = await MonitoredChannel.objects.aget_or_create(username=channel_username)

    if created:
        await update.message.reply_text(f"✅ کانال @{channel_username} با موفقیت اضافه شد.")
    else:
        await update.message.reply_text(f"⚠️ کانال @{channel_username} از قبل وجود داشت.")

    # Return to main admin menu
    await update.message.reply_text(
        "👑 پنل ادمین:", reply_markup=admin_main_keyboard()
    )
    return ADMIN_MAIN


async def admin_channels_remove_username_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin channel remove username input."""
    if not update.message or not update.message.text:
        return ADMIN_CHANNELS_REMOVE_USERNAME

    channel_username = update.message.text.lstrip("@").strip()
    if not channel_username:
        await update.message.reply_text("نام کاربری نامعتبر است. لطفاً دوباره تلاش کنید.")
        return ADMIN_CHANNELS_REMOVE_USERNAME

    from monitoring.models import MonitoredChannel

    try:
        channel = await MonitoredChannel.objects.aget(username=channel_username)
        await channel.adelete()
        await update.message.reply_text(f"🗑 کانال @{channel_username} با موفقیت حذف شد.")
    except MonitoredChannel.DoesNotExist:
        await update.message.reply_text(f"❌ کانال @{channel_username} یافت نشد.")

    # Return to main admin menu
    await update.message.reply_text(
        "👑 پنل ادمین:", reply_markup=admin_main_keyboard()
    )
    return ADMIN_MAIN


async def admin_cancel_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle admin cancel command."""
    if update.message:
        await update.message.reply_text("خروج از حالت ادمین انجام شد.")
    return ConversationHandler.END


# Helper functions for admin callbacks
async def _handle_channels_list(query: "CallbackQuery") -> None:
    """Handle channels list callback."""
    from monitoring.models import MonitoredChannel

    channels = MonitoredChannel.objects.all()
    count = await sync_to_async(channels.count)()

    if count == 0:
        await query.answer("هیچ کانالی برای مانیتورینگ ثبت نشده است.", show_alert=True)
        return

    message = "📜 لیست کانال‌های در حال مانیتور:\n\n"
    channel_list = []
    for channel in await sync_to_async(list)(channels):
        channel_list.append(f"\\- `@{channel.username}`")

    message += "\n".join(channel_list)

    keyboard = [
        [
            InlineKeyboardButton(
                "⬅️ بازگشت به مدیریت کانال‌ها", callback_data="admin:channels"
            )
        ]
    ]
    await query.edit_message_text(
        message, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _handle_stats(query: "CallbackQuery") -> None:
    """Handle stats callback."""
    total_users = await sync_to_async(UserProfile.objects.count)()
    total_sessions = await sync_to_async(ChatSession.objects.count)()
    total_messages = await sync_to_async(ChatMessage.objects.count)()
    total_docs = await sync_to_async(KnowledgeDocument.objects.count)()
    indexed_docs = await sync_to_async(
        KnowledgeDocument.objects.filter(indexed_in_rag=True).count
    )()

    today = timezone.now().date()

    def _today_counts():
        msgs_today = ChatMessage.objects.filter(created_at__date=today).count()
        sessions_today = ChatSession.objects.filter(created_at__date=today).count()
        docs_today = KnowledgeDocument.objects.filter(created_at__date=today).count()
        return msgs_today, sessions_today, docs_today

    msgs_today, sessions_today, docs_today = await sync_to_async(_today_counts)()

    rag_status = "نامشخص"
    rag_latency = None
    try:
        rag = RAGClient()
        start = time.time()
        await rag.search(query="ping", top_k=1)
        rag_latency = round((time.time() - start) * 1000, 2)
        rag_status = "سالم ✅"
    except (RAGServiceError, Exception):
        rag_status = "خطا ❌"

    text = (
        "📊 آمار کلی بات:\n"
        f"- کاربران تلگرام (کل): {total_users}\n"
        f"- سشن‌های چت (کل): {total_sessions}\n"
        f"- پیام‌ها (کل): {total_messages}\n"
        f"- اسناد دانش (کل): {total_docs}\n"
        f"- اسناد ایندکس‌شده در RAG: {indexed_docs}\n\n"
        "📅 امروز:\n"
        f"- پیام‌ها: {msgs_today}\n"
        f"- سشن‌های جدید: {sessions_today}\n"
        f"- اسناد جدید: {docs_today}\n\n"
        "🧠 وضعیت سرویس RAG:\n"
        f"- وضعیت: {rag_status}\n"
    )
    if rag_latency is not None:
        text += f"- تاخیر تقریبی جستجو: {rag_latency} ms\n"

    await query.edit_message_text(
        escape_markdown_v2(text),
        reply_markup=admin_main_keyboard(),
        parse_mode="MarkdownV2",
    )


async def _handle_push_unindexed(query: "CallbackQuery") -> None:
    """Handle push unindexed documents callback."""
    doc_ids = list(
        await sync_to_async(
            lambda: list(
                KnowledgeDocument.objects.filter(indexed_in_rag=False).values_list(
                    "id", flat=True
                )
            )
        )()
    )
    for doc_id in doc_ids:
        push_document_to_rag.delay(doc_id)
    await query.edit_message_text(
        f"📤 {len(doc_ids)} سند در صف ارسال به RAG قرار گرفت.",
        reply_markup=admin_main_keyboard(),
    )


async def _handle_reprocess_all(query: "CallbackQuery") -> None:
    """Handle reprocess all documents callback."""
    doc_ids = list(
        await sync_to_async(
            lambda: list(
                KnowledgeDocument.objects.filter(indexed_in_rag=True).values_list(
                    "id", flat=True
                )
            )
        )()
    )
    for doc_id in doc_ids:
        reprocess_document_in_rag.delay(doc_id)
    await query.edit_message_text(
        f"🔄 درخواست بازپردازش برای {len(doc_ids)} سند در صف قرار گرفت.",
        reply_markup=admin_main_keyboard(),
    )


async def _show_docs_list(query: "CallbackQuery", page: int = 0, page_size: int = 10) -> None:
    """Display paginated list of documents."""
    try:
        def _get_docs():
            return list(
                KnowledgeDocument.objects.order_by("-created_at")
                .values("id", "title", "source_url", "indexed_in_rag", "created_at")[
                    page * page_size : (page + 1) * page_size
                ]
            )

        def _get_total():
            return KnowledgeDocument.objects.count()

        docs = await sync_to_async(_get_docs)()
        total = await sync_to_async(_get_total)()

        if not docs and page > 0:
            # If page is empty but not first page, go back to first page
            page = 0
            docs = await sync_to_async(_get_docs)()

        if not docs:
            await query.edit_message_text(
                "📋 هیچ سندی یافت نشد.",
                reply_markup=admin_docs_keyboard(),
            )
            return

        text_lines = ["📋 لیست اسناد دانش:\n"]
        keyboard = []

        for doc in docs:
            doc_id = doc["id"]
            title = doc["title"][:50] + ("..." if len(doc["title"]) > 50 else "")
            indexed = "✅" if doc["indexed_in_rag"] else "❌"
            source = doc["source_url"] or "متن"
            created = (
                doc["created_at"].strftime("%Y-%m-%d")
                if doc["created_at"]
                else "نامشخص"
            )
            text_lines.append(
                f"{indexed} [{doc_id}] {title}\n   منبع: {source} | تاریخ: {created}"
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🗑️ حذف [{doc_id}]",
                        callback_data=f"admin:delete_doc:{doc_id}",
                    )
                ]
            )

        text = "\n".join(text_lines)
        text += f"\n\n📄 صفحه {page + 1} از {(total + page_size - 1) // page_size or 1}"

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    "⬅️ قبلی", callback_data=f"admin:list_docs:{page - 1}"
                )
            )
        if (page + 1) * page_size < total:
            nav_buttons.append(
                InlineKeyboardButton(
                    "➡️ بعدی", callback_data=f"admin:list_docs:{page + 1}"
                )
            )
        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append(
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="admin:docs")]
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.exception("Error showing docs list: %s", e)
        await query.answer("❌ خطا در نمایش لیست اسناد.", show_alert=True)


async def _delete_document(query: "CallbackQuery", doc_id: int) -> None:
    """Show confirmation dialog for deleting a document."""
    try:
        doc = await sync_to_async(KnowledgeDocument.objects.get)(id=doc_id)
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ بله، حذف کن",
                    callback_data=f"admin:confirm_delete:{doc_id}",
                ),
                InlineKeyboardButton(
                    "❌ انصراف",
                    callback_data="admin:list_docs:0",
                ),
            ]
        ]
        await query.edit_message_text(
            f"⚠️ آیا مطمئن هستید که می‌خواهید این سند را حذف کنید؟\n\n"
            f"📄 عنوان: {doc.title}\n"
            f"🆔 شناسه: {doc_id}\n"
            f"📊 ایندکس شده: {'بله' if doc.indexed_in_rag else 'خیر'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except KnowledgeDocument.DoesNotExist:
        await query.answer("❌ سند یافت نشد.", show_alert=True)
    except Exception as e:
        logger.exception("Error preparing delete confirmation: %s", e)
        await query.answer("❌ خطا در آماده‌سازی حذف.", show_alert=True)


async def _confirm_delete_document(query: "CallbackQuery", doc_id: int) -> None:
    """Actually delete the document."""
    try:
        doc = await sync_to_async(KnowledgeDocument.objects.get)(id=doc_id)
        title = doc.title
        await sync_to_async(doc.delete)()
        logger.info("Admin deleted KnowledgeDocument id=%s title=%r", doc_id, title)
        await query.answer("✅ سند با موفقیت حذف شد.", show_alert=True)
        # Refresh the list (go back to first page)
        await _show_docs_list(query, page=0)
    except KnowledgeDocument.DoesNotExist:
        await query.answer("❌ سند یافت نشد.", show_alert=True)
    except Exception as e:
        logger.exception("Error deleting document: %s", e)
        await query.answer("❌ خطا در حذف سند.", show_alert=True)

