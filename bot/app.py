import logging
import os
import re
import time
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


from core.models import ChatSession, KnowledgeDocument, UserProfile
from core.services.langgraph_pipeline import run_graph
from core.services.rag_client import RAGClient, RAGClientError
from core.tasks import push_document_to_rag, reprocess_document_in_rag

logger = logging.getLogger(__name__)


# ---- Admin states ----
(
    ADMIN_MAIN,
    ADMIN_NEW_DOC_TITLE,
    ADMIN_NEW_DOC_CONTENT,
    ADMIN_NEW_DOC_SOURCE,
    ADMIN_NEW_URL_DOC_URL,
    ADMIN_NEW_URL_DOC_TITLE,
    ADMIN_LIST_DOCS,
    ADMIN_CHANNELS_ADD_USERNAME,
    ADMIN_CHANNELS_REMOVE_USERNAME,
) = range(9)


WELCOME = (
    "سلام! من دستیار هوشمند دانشجویی شریف هستم. \n"
    "سوالت رو بپرس تا با استفاده از اسناد دانشگاه بهت کمک کنم.\n"
    "دستورات: /help | /reset"
)

HELP_TEXT = (
    "راهنما:\n"
    "- پیام‌تان را بفرستید تا پاسخ مبتنی بر RAG دریافت کنید.\n"
    "- /reset: شروع گفتگوی جدید و پاک‌سازی زمینه فعلی.\n"
    "- اگر پاسخ مبهم بود، سؤال را دقیق‌تر مطرح کنید."
)


def _get_admin_ids() -> set[str]:
    """
    Read allowed admin Telegram IDs from settings / env.
    Example: ADMIN_TELEGRAM_IDS="123456,789012"
    """
    raw = getattr(settings, "ADMIN_TELEGRAM_IDS", None) or os.getenv(
        "ADMIN_TELEGRAM_IDS", ""
    )
    return {s.strip() for s in raw.split(",") if s.strip()}


def _format_answer_markdown_to_html(text: str) -> str:
    """
    Convert lightweight Markdown-style bold (**text**) in LLM output
    to Telegram HTML format (<b>text</b>) and escape HTML-sensitive chars.
    Preserves existing HTML links (<a href="...">...</a>).
    """
    import re

    # First, protect existing HTML links from escaping
    link_pattern = r'<a href="([^"]+)">([^<]+)</a>'
    links = []

    def replace_link(match):
        links.append((match.group(0), match.group(1), match.group(2)))
        return f"__LINK_PLACEHOLDER_{len(links)-1}__"

    # Replace links with placeholders
    text = re.sub(link_pattern, replace_link, text)

    # Escape HTML-sensitive chars (but not in links)
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    # Convert markdown bold to HTML
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Restore links (they're already properly formatted)
    for idx, (original, url, link_text) in enumerate(links):
        # Unescape the link parts
        url = url.replace("&amp;", "&").replace(
            "&lt;", "<").replace("&gt;", ">")
        link_text = link_text.replace("&amp;", "&").replace(
            "&lt;", "<").replace("&gt;", ">")
        text = text.replace(
            f"__LINK_PLACEHOLDER_{idx}__", f'<a href="{url}">{link_text}</a>')

    return text


def _escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2 format.
    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = ['_', '*', '[', ']',
                     '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def _get_profile_and_session(update: Update) -> ChatSession:
    User = get_user_model()
    tg_user = update.effective_user
    username = f"tg_{tg_user.id}"
    user, _ = await sync_to_async(User.objects.get_or_create)(username=username)
    try:
        user.set_unusable_password()
        await sync_to_async(user.save)(update_fields=["password"])
    except Exception:
        pass

    try:
        profile = await sync_to_async(UserProfile.objects.get)(
            telegram_id=str(tg_user.id)
        )
    except UserProfile.DoesNotExist:
        profile = UserProfile(
            user=user,
            telegram_id=str(tg_user.id),
            display_name=tg_user.full_name,
        )
        await sync_to_async(profile.save)()

    try:
        session = await sync_to_async(ChatSession.objects.get)(
            user_profile=profile, is_active=True
        )
    except ChatSession.DoesNotExist:
        session = ChatSession(user_profile=profile, is_active=True, title=None)
        await sync_to_async(session.save)()
    return session


@dataclass(frozen=True)
class SharifBotConfig:
    token: str
    webhook_url: str | None = None


class SharifBot:

    def __init__(self, config: SharifBotConfig) -> None:
        self.config = config
        self.application: Application = Application.builder().token(config.token).build()

    # -------- Admin helpers / UI --------
    def _is_admin(self, update: Update) -> bool:
        tg_user = update.effective_user
        return bool(tg_user) and str(tg_user.id) in _get_admin_ids()

    def _admin_main_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("📚 مدیریت اسناد دانش",
                                  callback_data="admin:docs")],
            [InlineKeyboardButton("📡 مدیریت کانال‌ها",
                                  callback_data="admin:channels")],
            [InlineKeyboardButton(
                "📊 آمار کلی بات", callback_data="admin:stats")],
            [InlineKeyboardButton("❌ خروج از حالت ادمین",
                                  callback_data="admin:exit")],
        ]
        return InlineKeyboardMarkup(keyboard)

    # -------- Handlers --------
    async def admin_entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
            await update.message.reply_text("⚠️ شما دسترسی ادمین برای این بات را ندارید.")
            return ConversationHandler.END

        await update.message.reply_text(
            "👑 به پنل ادمین بات خوش آمدید.\n"
            "از دکمه‌های زیر برای مدیریت بات استفاده کنید:",
            reply_markup=self._admin_main_keyboard(),
        )
        return ADMIN_MAIN

    async def admin_main_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            keyboard = [
                [InlineKeyboardButton(
                    "➕ سند متنی جدید", callback_data="admin:create_doc_text")],
                [
                    InlineKeyboardButton(
                        "📤 ارسال اسناد ایندکس‌نشده به RAG",
                        callback_data="admin:push_unindexed",
                    )
                ],
                [InlineKeyboardButton(
                    "➕ سند از لینک وب‌سایت", callback_data="admin:create_doc_url")],
                [InlineKeyboardButton(
                    "🔄 بازپردازش همه اسناد ایندکس‌شده", callback_data="admin:reprocess_all")],
                [InlineKeyboardButton(
                    "📋 لیست و حذف اسناد", callback_data="admin:list_docs:0")],
                [InlineKeyboardButton(
                    "⬅️ بازگشت", callback_data="admin:back_main")],
            ]
            await query.edit_message_text(
                "📚 مدیریت اسناد دانش:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return ADMIN_MAIN

        if data == "admin:back_main":
            await query.edit_message_text("👑 پنل ادمین:", reply_markup=self._admin_main_keyboard())
            return ADMIN_MAIN

        if data == "admin:channels":
            keyboard = [
                [InlineKeyboardButton(
                    "➕ افزودن کانال", callback_data="admin:channels:add")],
                [InlineKeyboardButton(
                    "🗑️ حذف کانال", callback_data="admin:channels:remove")],
                [InlineKeyboardButton(
                    "📜 لیست کانال‌ها", callback_data="admin:channels:list")],
                [InlineKeyboardButton(
                    "⬅️ بازگشت", callback_data="admin:back_main")],
            ]
            await query.edit_message_text(
                "📡 مدیریت کانال‌ها:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return ADMIN_MAIN

        if data == "admin:channels:list":
            # Re-implement list_channels logic to work with callbacks
            from monitoring.models import MonitoredChannel
            channels = MonitoredChannel.objects.all()
            count = await channels.acount()

            if count == 0:
                await query.answer("هیچ کانالی برای مانیتورینگ ثبت نشده است.", show_alert=True)
                return ADMIN_MAIN

            message = "📜 لیست کانال‌های در حال مانیتور:\n\n"
            channel_list = []
            async for channel in channels:
                # MarkdownV2 needs escaping for characters like '_'
                username_escaped = channel.username.replace("_", "\\_")
                channel_list.append(f"- `@{username_escaped}`")

            message += "\n".join(channel_list)

            keyboard = [
                [InlineKeyboardButton(
                    "⬅️ بازگشت به مدیریت کانال‌ها", callback_data="admin:channels")]
            ]
            await query.edit_message_text(message, parse_mode='MarkdownV2', reply_markup=InlineKeyboardMarkup(keyboard))
            return ADMIN_MAIN

        if data == "admin:channels:add":
            await query.edit_message_text("لطفاً نام کاربری کانال جدید را برای افزودن ارسال کنید:")
            return ADMIN_CHANNELS_ADD_USERNAME

        if data == "admin:channels:remove":
            await query.edit_message_text("لطفاً نام کاربری کانال را برای حذف ارسال کنید:")
            return ADMIN_CHANNELS_REMOVE_USERNAME

        if data == "admin:stats":
            from core.models import ChatMessage as CM

            total_users = await sync_to_async(UserProfile.objects.count)()
            total_sessions = await sync_to_async(ChatSession.objects.count)()
            total_messages = await sync_to_async(CM.objects.count)()
            total_docs = await sync_to_async(KnowledgeDocument.objects.count)()
            indexed_docs = await sync_to_async(
                KnowledgeDocument.objects.filter(indexed_in_rag=True).count
            )()

            today = timezone.now().date()

            def _today_counts():
                msgs_today = CM.objects.filter(created_at__date=today).count()
                sessions_today = ChatSession.objects.filter(
                    created_at__date=today).count()
                docs_today = KnowledgeDocument.objects.filter(
                    created_at__date=today).count()
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
            except (RAGClientError, Exception):
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
                _escape_markdown_v2(text),
                reply_markup=self._admin_main_keyboard(),
                parse_mode='MarkdownV2'
            )
            return ADMIN_MAIN

        if data == "admin:push_unindexed":
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
                reply_markup=self._admin_main_keyboard(),
            )
            return ADMIN_MAIN

        if data == "admin:reprocess_all":
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
                reply_markup=self._admin_main_keyboard(),
            )
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
            await self._show_docs_list(query, page)
            return ADMIN_LIST_DOCS

        # Handle delete doc: admin:delete_doc:123
        if data.startswith("admin:delete_doc:"):
            try:
                doc_id = int(data.split(":")[-1])
            except (ValueError, IndexError):
                await query.answer("❌ شناسه سند نامعتبر است.", show_alert=True)
                return ADMIN_MAIN
            await self._delete_document(query, doc_id)
            return ADMIN_LIST_DOCS

        # Handle confirm delete: admin:confirm_delete:123
        if data.startswith("admin:confirm_delete:"):
            try:
                doc_id = int(data.split(":")[-1])
            except (ValueError, IndexError):
                await query.answer("❌ شناسه سند نامعتبر است.", show_alert=True)
                return ADMIN_MAIN
            await self._confirm_delete_document(query, doc_id)
            return ADMIN_LIST_DOCS

        return ADMIN_MAIN

    async def admin_new_doc_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
            await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
            return ConversationHandler.END

        title = (update.message.text or "").strip()
        if not title:
            await update.message.reply_text("❗ لطفاً یک عنوان معتبر ارسال کنید.")
            return ADMIN_NEW_DOC_TITLE

        context.user_data["new_doc_title"] = title
        await update.message.reply_text("متن کامل سند را ارسال کنید:")
        return ADMIN_NEW_DOC_CONTENT

    async def admin_new_doc_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
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

    async def admin_new_doc_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
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
                logger.info(
                    "Queued push_document_to_rag for doc id=%s", doc.id)
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

    async def admin_new_url_doc_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
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

    async def admin_new_url_doc_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return ConversationHandler.END
        if not self._is_admin(update):
            await update.message.reply_text("⚠️ دسترسی شما به حالت ادمین منقضی شده است.")
            return ConversationHandler.END

        title_text = (update.message.text or "").strip()
        source_url = context.user_data.get("new_doc_source_url", "")
        if not source_url:
            await update.message.reply_text("❗ لینک سند پیدا نشد، لطفاً دوباره تلاش کنید.")
            return ConversationHandler.END

        title = f"سند از وب‌سایت ({source_url})" if (
            not title_text or title_text == "-") else title_text

        logger.info(
            "Admin creating KnowledgeDocument (url). title=%r source_url=%r",
            title,
            source_url,
        )
        try:
            doc = await sync_to_async(KnowledgeDocument.objects.create)(
                title=title, content="", source_url=source_url, metadata={}
            )
            logger.info(
                "KnowledgeDocument (url) created successfully id=%s", doc.id)
            try:
                push_document_to_rag.delay(doc.id)
                logger.info(
                    "Queued push_document_to_rag for doc id=%s", doc.id)
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

    async def admin_channels_add_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return ADMIN_CHANNELS_ADD_USERNAME

        channel_username = update.message.text.lstrip('@').strip()
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
        await update.message.reply_text("👑 پنل ادمین:", reply_markup=self._admin_main_keyboard())
        return ADMIN_MAIN

    async def admin_channels_remove_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return ADMIN_CHANNELS_REMOVE_USERNAME

        channel_username = update.message.text.lstrip('@').strip()
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
        await update.message.reply_text("👑 پنل ادمین:", reply_markup=self._admin_main_keyboard())
        return ADMIN_MAIN

    async def admin_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message:
            await update.message.reply_text("خروج از حالت ادمین انجام شد.")
        return ConversationHandler.END

    async def _show_docs_list(self, query, page: int = 0, page_size: int = 10):
        """Display paginated list of documents."""
        try:
            def _get_docs():
                return list(
                    KnowledgeDocument.objects.order_by("-created_at")
                    .values("id", "title", "source_url", "indexed_in_rag", "created_at")[page * page_size: (page + 1) * page_size]
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
                    reply_markup=self._admin_docs_keyboard(),
                )
                return

            text_lines = ["📋 لیست اسناد دانش:\n"]
            keyboard = []

            for doc in docs:
                doc_id = doc["id"]
                title = doc["title"][:50] + \
                    ("..." if len(doc["title"]) > 50 else "")
                indexed = "✅" if doc["indexed_in_rag"] else "❌"
                source = doc["source_url"] or "متن"
                created = doc["created_at"].strftime(
                    "%Y-%m-%d") if doc["created_at"] else "نامشخص"
                text_lines.append(
                    f"{indexed} [{doc_id}] {title}\n   منبع: {source} | تاریخ: {created}")
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑️ حذف [{doc_id}]",
                        callback_data=f"admin:delete_doc:{doc_id}",
                    )
                ])

            text = "\n".join(text_lines)
            text += f"\n\n📄 صفحه {page + 1} از {(total + page_size - 1) // page_size or 1}"

            # Pagination buttons
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton(
                        "⬅️ قبلی", callback_data=f"admin:list_docs:{page - 1}")
                )
            if (page + 1) * page_size < total:
                nav_buttons.append(
                    InlineKeyboardButton(
                        "➡️ بعدی", callback_data=f"admin:list_docs:{page + 1}")
                )
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([
                InlineKeyboardButton("⬅️ بازگشت", callback_data="admin:docs")
            ])

            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.exception("Error showing docs list: %s", e)
            await query.answer("❌ خطا در نمایش لیست اسناد.", show_alert=True)

    async def _delete_document(self, query, doc_id: int):
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
                        callback_data=f"admin:list_docs:0",
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

    async def _confirm_delete_document(self, query, doc_id: int):
        """Actually delete the document."""
        try:
            doc = await sync_to_async(KnowledgeDocument.objects.get)(id=doc_id)
            title = doc.title
            await sync_to_async(doc.delete)()
            logger.info(
                "Admin deleted KnowledgeDocument id=%s title=%r", doc_id, title)
            await query.answer("✅ سند با موفقیت حذف شد.", show_alert=True)
            # Refresh the list (go back to first page)
            await self._show_docs_list(query, page=0)
        except KnowledgeDocument.DoesNotExist:
            await query.answer("❌ سند یافت نشد.", show_alert=True)
        except Exception as e:
            logger.exception("Error deleting document: %s", e)
            await query.answer("❌ خطا در حذف سند.", show_alert=True)

    def _admin_docs_keyboard(self) -> InlineKeyboardMarkup:
        """Helper to return admin docs menu keyboard."""
        keyboard = [
            [InlineKeyboardButton(
                "➕ سند متنی جدید", callback_data="admin:create_doc_text")],
            [
                InlineKeyboardButton(
                    "📤 ارسال اسناد ایندکس‌نشده به RAG",
                    callback_data="admin:push_unindexed",
                )
            ],
            [InlineKeyboardButton(
                "➕ سند از لینک وب‌سایت", callback_data="admin:create_doc_url")],
            [InlineKeyboardButton(
                "🔄 بازپردازش همه اسناد ایندکس‌شده", callback_data="admin:reprocess_all")],
            [InlineKeyboardButton(
                "📋 لیست و حذف اسناد", callback_data="admin:list_docs:0")],
            [InlineKeyboardButton(
                "⬅️ بازگشت", callback_data="admin:back_main")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _get_profile_and_session(update)
        if update.message:
            await update.message.reply_text(WELCOME, parse_mode="HTML")

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text(HELP_TEXT, parse_mode="HTML")

    async def reset_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Reset chat session - always works, even in conversations."""
        if not update.message:
            return

        # Clear any conversation state
        if context.user_data:
            context.user_data.clear()

        session = await _get_profile_and_session(update)
        await sync_to_async(ChatSession.objects.filter(id=session.id).update)(is_active=False)
        new_session = ChatSession(
            user_profile=session.user_profile, is_active=True)
        await sync_to_async(new_session.save)()

        logger.info(
            "User %s reset chat session. New session id=%s",
            update.effective_user.id if update.effective_user else "unknown",
            new_session.id,
        )

        await update.message.reply_text(
            "✅ گفتگوی جدید شروع شد. لطفاً سؤال خود را بپرسید.", parse_mode="HTML"
        )

        # Return END to exit any active conversation
        return ConversationHandler.END

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        session = await _get_profile_and_session(update)
        user_text = update.message.text or ""
        user_id = update.effective_user.id if update.effective_user else "unknown"

        logger.info(
            "Received message from user %s (session %s): %s",
            user_id,
            session.id,
            (user_text[:100] + "...") if len(user_text) > 100 else user_text,
        )

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
            formatted = _format_answer_markdown_to_html(answer)
            await update.message.reply_text(formatted, parse_mode="HTML")
        except Exception as e:
            logger.exception(
                "Pipeline error for user %s (session %s): %s", user_id, session.id, e)
            await update.message.reply_text(
                "متاسفانه خطایی در پردازش پیام شما رخ داد. لطفاً کمی بعد دوباره تلاش کنید."
            )

    async def debug_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query and update.effective_user:
            logger.info(
                "DEBUG: Callback query received: %s from user %s",
                query.data,
                update.effective_user.id,
            )

    def setup_handlers(self) -> None:
        admin_conv = ConversationHandler(
            entry_points=[CommandHandler("admin", self.admin_entry)],
            states={
                ADMIN_MAIN: [CallbackQueryHandler(self.admin_main_callback, pattern=r"^admin:")],
                ADMIN_LIST_DOCS: [CallbackQueryHandler(self.admin_main_callback, pattern=r"^admin:")],
                ADMIN_NEW_DOC_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_new_doc_title)
                ],
                ADMIN_NEW_DOC_CONTENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_new_doc_content)
                ],
                ADMIN_NEW_DOC_SOURCE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_new_doc_source)
                ],
                ADMIN_NEW_URL_DOC_URL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_new_url_doc_url)
                ],
                ADMIN_NEW_URL_DOC_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_new_url_doc_title)
                ],
                ADMIN_CHANNELS_ADD_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_channels_add_username)
                ],
                ADMIN_CHANNELS_REMOVE_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   self.admin_channels_remove_username)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.admin_cancel),
                # Allow reset to exit admin conversation
                CommandHandler("reset", self.reset_cmd),
            ],
            name="admin_conversation",
            persistent=False,
        )

        # IMPORTANT: ConversationHandler must be added BEFORE the general MessageHandler
        # Add reset handler FIRST so it can work even if user is in a conversation
        self.application.add_handler(CommandHandler("reset", self.reset_cmd))
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_cmd))

        self.application.add_handler(admin_conv)
        self.application.add_handler(CallbackQueryHandler(self.debug_callback))
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.on_text))

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
