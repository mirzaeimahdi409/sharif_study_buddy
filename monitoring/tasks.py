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


# --- Async DB Helpers ---

@sync_to_async
def db_get_or_create_message(external_id, defaults):
    return IngestedTelegramMessage.objects.get_or_create(
        external_id=external_id,
        defaults=defaults
    )


@sync_to_async
def db_check_duplicate_content(content_hash, external_id):
    return IngestedTelegramMessage.objects.filter(
        content_hash=content_hash, ingested=True
    ).exclude(external_id=external_id).exists()


@sync_to_async
def db_save_record(record, update_fields):
    record.save(update_fields=update_fields)


async def ingest_message_to_kb_async(message: Message, channel_username: str):
    """
    Constructs and sends the message to the knowledge base API.
    Async version to avoid event loop conflicts when using RAGClient.
    """
    # Extract URLs from the original message text (before cleaning)
    raw_text = message.text or ""
    # Regex to find http/https URLs
    found_urls = re.findall(r'(https?://[^\s]+)', raw_text)
    urls_to_process = []
    for url in found_urls:
        # Simple cleanup of trailing punctuation often caught by regex
        # Added | and () to the list of chars to strip
        clean_url = url.rstrip('.,;:!?"\')>])|')
        # Skip Telegram links to avoid circular or useless ingestion
        if "t.me/" not in clean_url and "telegram.me/" not in clean_url:
            urls_to_process.append(clean_url)
    urls_to_process = list(set(urls_to_process))

    message_link = f"https://t.me/{channel_username}/{message.id}"
    external_id = f"telegram:{channel_username}:{message.id}"
    content_hash = _content_hash(message.text or "")

    # ---- Deduplication guard ----
    rec, created = await db_get_or_create_message(
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
        is_duplicate = await db_check_duplicate_content(content_hash, external_id)
        if is_duplicate:
            # Mark as "ingested" to avoid rechecking every run, but keep note.
            rec.ingested = True
            rec.ingested_at = timezone.now()
            rec.last_error = "Skipped due to duplicate content hash."
            await db_save_record(rec, update_fields=["ingested", "ingested_at", "last_error", "updated_at"])
            return

    # Clean text before sending to RAG
    cleaned_text = _clean_message_text(message.text or "")

    # Create a title from the first 100 characters of the CLEANED message
    title = cleaned_text[:100] if len(cleaned_text) > 100 else cleaned_text
    if len(cleaned_text) > 100:
        title += "..."

    # Use RAGClient for ingestion
    client = RAGClient()
    try:
        # Update attempt tracking
        rec.attempts = (rec.attempts or 0) + 1
        rec.last_attempt_at = timezone.now()
        rec.source_url = message_link
        rec.content_hash = content_hash
        await db_save_record(rec, update_fields=["attempts", "last_attempt_at", "source_url", "content_hash", "updated_at"])

        result = await client.ingest_channel_message(
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

        doc_id = result.get("id") or result.get("document_id")

        logger.info(
            "Successfully ingested message %s from %s (doc_id=%s)",
            message.id,
            channel_username,
            doc_id,
        )

        # Process any URLs found in the message
        for url in urls_to_process:
            try:
                logger.info(
                    f"Processing URL extracted from message {message.id}: {url}")
                url_res = await client.ingest_url(
                    url_to_fetch=url,
                    metadata={
                        "source": "telegram_link",
                        "original_channel": channel_username,
                        "original_message_id": message.id,
                        "original_message_url": message_link,
                    }
                )
                url_doc_id = url_res.get("id") or url_res.get("document_id")
                logger.info(
                    f"Successfully ingested extracted URL {url} (doc_id={url_doc_id})")
            except Exception as e:
                # Log warning but don't fail the message ingestion
                logger.warning(f"Failed to ingest extracted URL {url}: {e}")

        rec.ingested = True
        rec.ingested_at = timezone.now()
        rec.last_error = None
        if doc_id:
            rec.rag_document_id = str(doc_id)

        await db_save_record(rec, update_fields=[
            "ingested",
            "ingested_at",
            "last_error",
            "rag_document_id",
            "updated_at",
        ])

    except RAGServiceError as e:
        error_msg = str(e)
        logger.error(
            "Error ingesting message %s from %s: %s",
            message.id,
            channel_username,
            error_msg,
        )
        rec.last_error = error_msg
        await db_save_record(rec, update_fields=["last_error", "updated_at"])
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(
            "Unexpected error ingesting message %s from %s: %s",
            message.id,
            channel_username,
            error_msg,
        )
        rec.last_error = error_msg
        await db_save_record(rec, update_fields=["last_error", "updated_at"])
    finally:
        await client.close()

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
                # Run ingestion logic asynchronously
                await ingest_message_to_kb_async(message, channel_username)
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
    session_string = TelegramConfig.get_session_string()

    if not api_id or not api_hash:
        print("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured. Exiting.")
        return

    # Initialize Telegram Client
    from telethon.sessions import StringSession
    import os

    if session_string:
        # Use StringSession if available (avoids SQLite locking issues in containers)
        # print("Using StringSession for Telegram client.")
        client = TelegramClient(StringSession(
            session_string), api_id, api_hash)
    else:
        # Fallback to SQLite session file
        session_path = os.path.join(os.path.dirname(
            __file__), '..', 'sessions', 'telegram_session')
        # print(f"Using SQLite session file: {session_path}")
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
