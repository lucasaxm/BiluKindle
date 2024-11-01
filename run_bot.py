#!/usr/bin/env python3
import asyncio
import signal
import sys

from telegram.ext import ApplicationBuilder
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    TELETHON_SESSION_STRING,
    ALLOWED_USERS,
    print_config_status,
    setup_env
)
from src import MangaBot, setup_environment, __version__, managed_bot


async def get_verification_code():
    """Get verification code from user input"""
    return input('Please enter the verification code you received: ')


async def get_password():
    """Get 2FA password if needed"""
    return input('Please enter your 2FA password: ')


async def setup_telethon_client() -> TelegramClient:
    """Setup and authenticate Telethon client"""
    try:
        # Use StringSession for easier portability
        session = StringSession(TELETHON_SESSION_STRING)
        client = TelegramClient(session, TELEGRAM_API_ID, TELEGRAM_API_HASH)

        # Start the client
        print("Connecting to Telegram...")
        await client.connect()

        # If already authenticated, just return the client
        if await client.is_user_authorized():
            print("Already authenticated!")
            return client

        # Send code request
        print("Sending code request...")
        await client.send_code_request(TELEGRAM_PHONE)

        try:
            print("Signing in...")
            # Get the code from user input
            code = await get_verification_code()
            await client.sign_in(TELEGRAM_PHONE, code)

        except SessionPasswordNeededError:
            # 2FA is enabled
            password = await get_password()
            await client.sign_in(password=password)

        # Generate and print the session string
        if not TELETHON_SESSION_STRING:
            session_string = client.session.save()
            print("\nPlease add this to your .env file as TELETHON_SESSION_STRING:")
            print(session_string)
            print("\nThis will prevent you from needing to authenticate again.\n")

        return client

    except Exception as e:
        print(f"Error setting up Telethon client: {str(e)}")
        sys.exit(1)


async def main():
    print(f"Manga to Kindle Converter Bot v{__version__}")
    print("Initializing...")

    # Setup environment
    setup_env()
    setup_environment()

    # Validate configuration
    if not print_config_status():
        print("Please set the required environment variables and try again.")
        return

    # Setup Telethon client
    telethon_client = await setup_telethon_client()

    # Create application
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Initialize bot with handlers
    bot = MangaBot(
        application,
        telethon_client,
        ALLOWED_USERS
    )

    print("Bot started! Press Ctrl+C to exit.")

    # Use context manager for proper resource management
    async with managed_bot(application, telethon_client) as (app, client):
        try:
            # Start polling in the background
            await app.updater.start_polling(drop_pending_updates=True)

            # Create a shutdown event
            stop_event = asyncio.Event()

            def signal_handler():
                stop_event.set()

            # Handle interruption
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)

            # Wait until interrupted
            await stop_event.wait()

        except asyncio.CancelledError:
            print("\nShutdown received...")
        except KeyboardInterrupt:
            print("\nBot stopped by user.")
        finally:
            print("Cleaning up resources...")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
