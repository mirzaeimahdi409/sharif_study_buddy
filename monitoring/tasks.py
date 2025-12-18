import asyncio
import requests
from celery import shared_task
from django.conf import settings
from telethon import TelegramClient
from telethon.tl.types import Message

from .models import MonitoredChannel

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
        }
    }

    try:
        response = requests.post(
            settings.RAG_API_URL + '/knowledge/documents/ingest-channel-message/',
            json=payload
        )
        response.raise_for_status()
        print(
            f"✅ Successfully ingested message {message.id} from {channel_username}")
    except requests.exceptions.RequestException as e:
        print(
            f"❌ Error ingesting message {message.id} from {channel_username}: {e}")
        if hasattr(e.response, 'text'):
            print(f"   Response: {e.response.text}")

# --- Main Celery Task ---


async def _harvest_channel_async(client, channel_username):
    """Asynchronous logic to harvest a single channel."""
    print(f"--- Harvesting channel: {channel_username} ---")
    try:
        async for message in client.iter_messages(channel_username, limit=150):
            if is_message_relevant(message):
                ingest_message_to_kb(message, channel_username)
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
