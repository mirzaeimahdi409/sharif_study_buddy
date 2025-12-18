"""Keyboard markup definitions for the Telegram bot."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_keyboard() -> InlineKeyboardMarkup:
    """Main admin menu keyboard."""
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


def admin_docs_keyboard() -> InlineKeyboardMarkup:
    """Admin documents management keyboard."""
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


def admin_channels_keyboard() -> InlineKeyboardMarkup:
    """Admin channels management keyboard."""
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
    return InlineKeyboardMarkup(keyboard)
