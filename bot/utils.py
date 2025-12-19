"""Utility functions for the Telegram bot."""
import logging
import re
from typing import Set

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from telegram import Update

from core.models import ChatSession, UserProfile
from core.config import TelegramConfig

logger = logging.getLogger(__name__)


def get_admin_ids() -> Set[str]:
    """
    Read allowed admin Telegram IDs from settings / env.
    Example: ADMIN_TELEGRAM_IDS="123456,789012"
    """
    return TelegramConfig.get_admin_ids()


def format_answer_markdown_to_html(text: str) -> str:
    """
    Convert lightweight Markdown-style bold (**text**) in LLM output
    to Telegram HTML format (<b>text</b>) and escape HTML-sensitive chars.
    Preserves existing HTML links (<a href="...">...</a>).
    """
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


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2 format.
    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = ['_', '*', '[', ']',
                     '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def get_profile_and_session(update: Update) -> ChatSession:
    """Get or create user profile and active chat session."""
    from core.services import metrics
    
    User = get_user_model()
    tg_user = update.effective_user
    username = f"tg_{tg_user.id}"
    user, _ = await sync_to_async(User.objects.get_or_create)(username=username)
    try:
        user.set_unusable_password()
        await sync_to_async(user.save)(update_fields=["password"])
    except Exception:
        pass

    is_new_user = False
    try:
        profile = await sync_to_async(UserProfile.objects.get)(
            telegram_id=str(tg_user.id)
        )
    except UserProfile.DoesNotExist:
        is_new_user = True
        profile = UserProfile(
            user=user,
            telegram_id=str(tg_user.id),
            display_name=tg_user.full_name,
        )
        await sync_to_async(profile.save)()
        # Track new user
        metrics.new_users_total.inc()

    is_new_session = False
    try:
        session = await sync_to_async(ChatSession.objects.get)(
            user_profile=profile, is_active=True
        )
    except ChatSession.DoesNotExist:
        is_new_session = True
        session = ChatSession(user_profile=profile, is_active=True, title=None)
        await sync_to_async(session.save)()
        # Track new session
        metrics.user_sessions_total.inc()
    
    return session
