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
    bot_token = settings.TELEGRAM_BOT_TOKEN

    if not api_id or not api_hash:
        print("TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured. Exiting.")
        return

    if not bot_token:
        print("TELEGRAM_BOT_TOKEN is not configured. Exiting.")
        return

    # Use a session name as in the official Telethon docs:
    #   client = TelegramClient('session_name', api_id, api_hash)
    # Here we authenticate as a **bot** (no phone number) using:
    #   await client.start(bot_token=...)
    session_name = 'telegram_bot_session'

    client = TelegramClient(session_name, api_id, api_hash)

    async def main():
        """
        Use a **bot session** (no phone number) to harvest messages from channels.

        As shown in the Telethon README
        (`https://github.com/LonamiWebs/Telethon`), the recommended pattern is:

            from telethon import TelegramClient
            client = TelegramClient('session_name', api_id, api_hash)
            client.start()

        For bots, Telethon also supports:

            client = TelegramClient('session_name', api_id, api_hash)
            client.start(bot_token='YOUR_BOT_TOKEN')

        We follow the same approach here, but in an async Celery task:
        create the client once and then call `await client.start(bot_token=...)`
        so no interactive phone/OTP flow is needed, and the same `api_id` /
        `api_hash` pair is reused for the bot.
        """
        try:
            # This will authorize the bot using the configured token and will
            # also create/update the local session file `telegram_bot_session.session`.
            await client.start(bot_token=bot_token)

            tasks = [
                _harvest_channel_async(client, username) for username in channels
            ]
            await asyncio.gather(*tasks)
        finally:
            await client.disconnect()

    # Run the async main function
    asyncio.run(main())
