"""Constants for the Telegram bot."""

# Admin conversation states
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
    ADMIN_CHANNELS_ADD_MESSAGE_COUNT,
    ADMIN_BROADCAST_MENU,
    ADMIN_BROADCAST_FILTER_INPUT,
    ADMIN_BROADCAST_MESSAGE_INPUT,
    ADMIN_BROADCAST_CONFIRM,
) = range(14)

# Bot messages
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
