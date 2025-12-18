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
    """Constructs and sends the message to the knowledge base API."""
    message_link = f"https://t.me/{channel_username}/{message.id}"
    payload = {
        "document": {
            "text": message.text,
            "metadata": {
                "source": "telegram_channel",
                "channel": channel_username,
                "message_id": message.id,
                "message_link": message_link,
                "timestamp": message.date.isoformat(),
            }
        }
    }
    try:
        response = requests.post(
            settings.RAG_API_URL + '/documents/ingest-channel-message/', json=payload)
        response.raise_for_status()
        print(
            f"Successfully ingested message {message.id} from {channel_username}")
    except requests.exceptions.RequestException as e:
        print(f"Error ingesting message {message.id}: {e}")

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
    session_name = 'telegram_session'

    # Create the Telegram client as in the official docs:
    #   client = TelegramClient(name, api_id, api_hash)
    client = TelegramClient(session_name, api_id, api_hash)

    async def main():
        """
        Use an already-authorized user session to harvest messages from channels.

        This function assumes that the session file for `session_name` has been
        created beforehand (for example by running a one-off script that calls
        `client.start()` interactively, as shown in the Telethon quick-start).
        In a non-interactive environment (Celery worker) we only connect and
        check authorization; if the user is not authorized we log a message and
        stop without prompting for phone or bot token.
        See: https://docs.telethon.dev/en/stable/modules/client.html
        """
        try:
            await client.connect()

            if not await client.is_user_authorized():
                print(
                    "Telegram session is not authorized. "
                    "Please create it once manually using Telethon (client.start(phone=...)) "
                    "so that 'telegram_session' is stored, then rerun the worker."
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
