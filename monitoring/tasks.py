import asyncio
import hashlib
import re
import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async
from telethon import TelegramClient
from telethon.tl.types import Message

from .models import MonitoredChannel, IngestedTelegramMessage

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

    dedup_by_content = str(getattr(settings, "TELEGRAM_DEDUP_BY_CONTENT", "") or "").lower() in (
        "1", "true", "yes", "on"
    )
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

    # Create a title from the first 100 characters of the message
    title = message.text[:100] if len(message.text) > 100 else message.text
    if len(message.text) > 100:
        title += "..."

    payload = {
        "title": title,
        "text_content": message.text,
        "published_at": message.date.isoformat(),
        "source_url": message_link,
        "user_id": settings.RAG_USER_ID,
        # Must be one of the allowed values from the RAG API:
        #   support_assistant, telegram_bot
        "microservice": "telegram_bot",
        "metadata": {
            "source": "telegram_channel",
            "channel": channel_username,
            "message_id": message.id,
            "message_date": message.date.isoformat(),
            "external_id": external_id,
        }
    }

    try:
        rec.attempts = (rec.attempts or 0) + 1
        rec.last_attempt_at = timezone.now()
        rec.source_url = message_link
        rec.content_hash = content_hash
        rec.save(update_fields=["attempts", "last_attempt_at",
                 "source_url", "content_hash", "updated_at"])

        response = requests.post(
            settings.RAG_API_URL + '/knowledge/documents/ingest-channel-message/',
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        data = {}
        try:
            data = response.json() or {}
        except ValueError:
            data = {}

        doc_id = data.get("id") or data.get("document_id")

        print(
            f"✅ Successfully ingested message {message.id} from {channel_username} "
            f"(doc_id={doc_id})"
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
    except requests.exceptions.RequestException as e:
        print(
            f"❌ Error ingesting message {message.id} from {channel_username}: {e}")
        resp_text = None
        if hasattr(e, "response") and e.response is not None:
            try:
                resp_text = e.response.text
            except Exception:
                resp_text = None
        if resp_text:
            print(f"   Response: {resp_text}")

        rec.last_error = f"{e} | response={resp_text}" if resp_text else str(e)
        rec.save(update_fields=["last_error", "updated_at"])

# --- Main Celery Task ---


async def _harvest_channel_async(client, channel_username):
    """Asynchronous logic to harvest a single channel."""
    print(f"--- Harvesting channel: {channel_username} ---")
    try:
        async for message in client.iter_messages(channel_username, limit=150):
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
    channels = MonitoredChannel.objects.values_list('username', flat=True)
    if not channels:
        print("No channels to monitor. Exiting.")
        return

    # Get Telegram credentials from Django settings
    api_id = settings.TELEGRAM_API_ID
    api_hash = settings.TELEGRAM_API_HASH

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
                _harvest_channel_async(client, username) for username in channels
            ]
            await asyncio.gather(*tasks)
        finally:
            await client.disconnect()

    # Run the async main function
    asyncio.run(main())
