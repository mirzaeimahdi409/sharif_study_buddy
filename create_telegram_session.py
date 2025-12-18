#!/usr/bin/env python
"""
One-time script to create a Telegram user session file.

This script must be run ONCE, interactively, to authorize your Telegram account.
After running this, a 'telegram_session.session' file will be created, and the
Celery worker will be able to use it without any further interaction.

Usage:
    python create_telegram_session.py

You will be prompted for:
1. Your phone number (international format, e.g. +989123456789)
2. The login code sent to your Telegram app

After successful authorization, the session file will be saved and you can
restart your Celery worker.
"""
from telethon import TelegramClient
from django.conf import settings
import os
import sys
import django
import asyncio

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sharif_assistant.settings")
django.setup()


async def main():
    api_id = settings.TELEGRAM_API_ID
    api_hash = settings.TELEGRAM_API_HASH

    # Create sessions directory if it doesn't exist
    sessions_dir = os.path.join(os.path.dirname(__file__), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    # Session file path - must match monitoring/tasks.py
    session_path = os.path.join(sessions_dir, "telegram_session")

    if not api_id or not api_hash:
        print(
            "❌ Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in your .env file.")
        sys.exit(1)

    print("=" * 60)
    print("Telegram Session Creator")
    print("=" * 60)
    print(f"\nUsing API ID: {api_id}")
    print(f"Session path: {session_path}\n")

    client = TelegramClient(session_path, api_id, api_hash)

    # Start the client interactively
    # This will prompt for phone number and login code
    await client.start()

    # Test if authorization worked
    me = await client.get_me()
    print("\n" + "=" * 60)
    print("✅ SUCCESS! Session created and authorized.")
    print("=" * 60)
    print(f"Logged in as: {me.first_name} {me.last_name or ''}")
    print(f"Username: @{me.username}" if me.username else "No username")
    print(f"Phone: {me.phone}\n")
    print(f"Session file saved at: {session_path}.session")
    print("You can now restart your Celery worker and it will use this session.")
    print("=" * 60)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
