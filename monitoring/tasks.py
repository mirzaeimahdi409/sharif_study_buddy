import asyncio
import hashlib
import re
import logging
from celery import shared_task
from django.utils import timezone
from asgiref.sync import sync_to_async
from telethon import TelegramClient
from telethon.tl.types import Message

from .models import MonitoredChannel, IngestedTelegramMessage
from core.services.rag_client import RAGClient
from core.exceptions import RAGServiceError
from core.config import TelegramConfig, RAGConfig

logger = logging.getLogger(__name__)

# --- Smart Filtering (same as before) ---


def is_message_relevant(message: Message) -> bool:
    """A smart filter to decide if a message is worth ingesting."""
    if not message.text or len(message.text.split()) < 10:
        return False
    ad_keywords = ['تبلیغ', 'خرید', 'فروش', 'سفارش', 'تخفیف']
    if any(keyword in message.text for keyword in ad_keywords):
        return False
    if message.is_reply:
        return False
    return True

# --- API Ingestion (same as before) ---


def _normalize_text(text: str) -> str:
    # Collapse whitespace and trim; keep case (Persian) as-is.
    return re.sub(r"\s+", " ", (text or "").strip())


def _content_hash(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _clean_message_text(raw: str) -> str:
    """
    Clean Telegram message text before sending to RAG (channel-agnostic).

    - Remove simple Markdown formatting (**bold**, __italic__, `code`)
    - Strip common channel signatures like '🆔 @Something' یا خطوطی که فقط '@channel' هستند
    - Collapse excessive blank lines and spaces
    """
    if not raw:
        return ""

    text = raw

    import re

    # Remove common channel tag / signature lines:
    #  - lines that start with emojis then @username (e.g. "🆔 @SharifDaily")
    #  - lines that are only @username
    #  - lines like "channel: @something"
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # pure @username
        if re.fullmatch(r"@[\w\d_]+", stripped):
            continue
        # emoji(s) + @username, e.g. "🆔 @SharifDaily"
        if re.fullmatch(r"[^\w@]*@[\w\d_]+", stripped):
            continue
        # patterns like "ID: @something" / "Channel: @something"
        if re.fullmatch(r".{0,10}@[\w\d_]+", stripped):
            # short label + handle, usually a footer
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Remove basic markdown markers while keeping content
    # **bold** or __italic__
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    # inline code `code`
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Collapse 3+ newlines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing whitespace on each line
    text = "\n".join(l.rstrip() for l in text.splitlines())
    return text.strip()


def ingest_message_to_kb(message: Message, channel_username: str):
    """
    Constructs and sends the message to the knowledge base API.

    Uses the /api/knowledge/documents/ingest-channel-message/ endpoint which accepts:
    - title (required): Title for the message document
    - text_content (required): The full text content of the message
    - published_at (required): The original publication timestamp (ISO 8601 format)
    - source_url (required): A direct URL to the original message for citation
    - user_id (required): Owner user ID for access control
    - microservice (optional): Microservice name for scoping
    - metadata (optional): Additional JSON metadata
    """
    message_link = f"https://t.me/{channel_username}/{message.id}"
    external_id = f"telegram:{channel_username}:{message.id}"
    content_hash = _content_hash(message.text or "")

    # ---- Deduplication guard ----
    # 1) Strong dedupe by external_id (channel + message_id)
    # 2) Optional content-based dedupe (same normalized text) across all channels
    #    Enable by setting TELEGRAM_DEDUP_BY_CONTENT=1 in env.
    rec, created = IngestedTelegramMessage.objects.get_or_create(
        external_id=external_id,
        defaults={
            "channel_username": channel_username,
            "message_id": int(message.id),
            "source_url": message_link,
            "content_hash": content_hash,
        },
    )

    if rec.ingested:
        # Already ingested successfully.
        return

    dedup_by_content = TelegramConfig.get_dedup_by_content()
    if dedup_by_content:
        if IngestedTelegramMessage.objects.filter(
            content_hash=content_hash, ingested=True
        ).exclude(external_id=external_id).exists():
            # Mark as "ingested" to avoid rechecking every run, but keep note.
            rec.ingested = True
            rec.ingested_at = timezone.now()
            rec.last_error = "Skipped due to duplicate content hash."
            rec.save(update_fields=["ingested",
                     "ingested_at", "last_error", "updated_at"])
            return

    # Clean text before sending to RAG
    cleaned_text = _clean_message_text(message.text or "")

    # Create a title from the first 100 characters of the CLEANED message
    title = cleaned_text[:100] if len(cleaned_text) > 100 else cleaned_text
    if len(cleaned_text) > 100:
        title += "..."

    try:
        import time
        start_time = time.time()

        # Update attempt tracking
        rec.attempts = (rec.attempts or 0) + 1
        rec.last_attempt_at = timezone.now()
        rec.source_url = message_link
        rec.content_hash = content_hash
        rec.save(update_fields=["attempts", "last_attempt_at",
                 "source_url", "content_hash", "updated_at"])

        logger.info(
            "📤 Starting ingestion for message %s from %s (attempt #%s)",
            message.id,
            channel_username,
            rec.attempts,
            extra={
                "message_id": message.id,
                "channel": channel_username,
                "attempt": rec.attempts,
                "external_id": external_id,
                "content_hash": content_hash,
                "cleaned_text_length": len(cleaned_text),
                "title": title[:100] if title else None,
            }
        )

        # Use RAGClient for ingestion
        logger.debug("Creating RAGClient instance")
        client = RAGClient()
        logger.debug(
            "RAGClient created, calling ingest_channel_message_sync",
            extra={"base_url": client.base_url, "timeout": client.timeout}
        )

        result = client.ingest_channel_message_sync(
            title=title,
            text_content=cleaned_text,
            published_at=message.date.isoformat(),
            source_url=message_link,
            metadata={
                "source": "telegram_channel",
                "channel": channel_username,
                "message_id": message.id,
                "message_date": message.date.isoformat(),
                "external_id": external_id,
            },
        )

        ingestion_duration = time.time() - start_time
        logger.debug(
            f"Ingestion API call completed in {ingestion_duration:.2f}s")

        doc_id = result.get("id") or result.get("document_id")

        logger.info(
            "Successfully ingested message %s from %s (doc_id=%s)",
            message.id,
            channel_username,
            doc_id,
        )

        rec.ingested = True
        rec.ingested_at = timezone.now()
        rec.last_error = None
        if doc_id:
            rec.rag_document_id = str(doc_id)
        rec.save(
            update_fields=[
                "ingested",
                "ingested_at",
                "last_error",
                "rag_document_id",
                "updated_at",
            ]
        )
    except RAGServiceError as e:
        import time
        error_duration = time.time() - start_time if 'start_time' in locals() else None
        error_msg = str(e)
        logger.error(
            "❌ Error ingesting message %s from %s: %s (duration: %s)",
            message.id,
            channel_username,
            error_msg,
            f"{error_duration:.2f}s" if error_duration else "unknown",
            extra={
                "message_id": message.id,
                "channel": channel_username,
                "error": error_msg,
                "error_type": type(e).__name__,
                "duration": error_duration,
                "attempt": rec.attempts,
                "external_id": external_id,
            },
            exc_info=True
        )
        rec.last_error = error_msg
        rec.save(update_fields=["last_error", "updated_at"])
    except Exception as e:
        import time
        error_duration = time.time() - start_time if 'start_time' in locals() else None
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(
            "💥 Unexpected error ingesting message %s from %s: %s (duration: %s)",
            message.id,
            channel_username,
            error_msg,
            f"{error_duration:.2f}s" if error_duration else "unknown",
            extra={
                "message_id": message.id,
                "channel": channel_username,
                "error": error_msg,
                "error_type": type(e).__name__,
                "duration": error_duration,
                "attempt": rec.attempts,
                "external_id": external_id,
            }
        )
        rec.last_error = error_msg
        rec.save(update_fields=["last_error", "updated_at"])

# --- Main Celery Task ---


async def _harvest_channel_async(client, channel: MonitoredChannel):
    """Asynchronous logic to harvest a single channel."""
    channel_username = channel.username
    limit = channel.rag_message_count if channel.rag_message_count > 0 else None

    print(
        f"--- Harvesting channel: {channel_username} (limit: {limit or 'all'}) ---")
    try:
        async for message in client.iter_messages(channel_username, limit=limit):
            if is_message_relevant(message):
                # Run Django/requests-based ingestion in a sync thread
                await sync_to_async(
                    ingest_message_to_kb,
                    thread_sensitive=True,
                )(message, channel_username)
    except Exception as e:
        print(f"Could not process channel {channel_username}: {e}")


@shared_task
def harvest_channels_task():
    """The main Celery task to run the channel harvesting logic."""
    # Fetch channel list from the database
    channels = list(MonitoredChannel.objects.all())
    if not channels:
        print("No channels to monitor. Exiting.")
        return

    # Get Telegram credentials from config
    api_id = TelegramConfig.get_api_id()
    api_hash = TelegramConfig.get_api_hash()

    if not api_id or not api_hash:
        print("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured. Exiting.")
        return

    # Session file path (must match create_telegram_session.py)
    import os
    session_path = os.path.join(os.path.dirname(
        __file__), '..', 'sessions', 'telegram_session')

    # Create the Telegram client as in the official docs:
    #   client = TelegramClient('session_name', api_id, api_hash)
    # See: https://docs.telethon.dev/en/stable/basic/quick-start.html
    client = TelegramClient(session_path, api_id, api_hash)

    async def main():
        """
        Use an already-authorized user session to harvest messages from channels.

        This function assumes that the session file for `session_name` has been
        created beforehand by running `python create_telegram_session.py` once
        (which calls client.start() interactively with your phone number).

        In a non-interactive environment (Celery worker) we only connect and
        check authorization; if the user is not authorized we log a message and
        stop without prompting for phone or code.
        """
        try:
            await client.connect()

            if not await client.is_user_authorized():
                print(
                    "❌ Telegram session is not authorized. "
                    "Please run 'python create_telegram_session.py' once to create the session file, "
                    "then restart the worker."
                )
                return

            tasks = [
                _harvest_channel_async(client, channel) for channel in channels
            ]
            await asyncio.gather(*tasks)
        finally:
            await client.disconnect()

    # Run the async main function
    asyncio.run(main())
