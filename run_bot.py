#!/usr/bin/env python3
"""
Main entry point for the Manga to Kindle Converter Bot
"""

from telegram.ext import ApplicationBuilder

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USERS,
    KINDLE_EMAIL,
    SENDER_EMAIL,
    SENDER_PASSWORD,
    print_config_status,
    setup_env
)
from src import MangaBot, setup_environment, __version__


def main():
    print(f"Manga to Kindle Converter Bot v{__version__}")
    print("Initializing...")

    # Setup environment
    setup_env()
    setup_environment()

    # Validate configuration
    if not print_config_status():
        print("Please set the required environment variables and try again.")
        return

    # Create application
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Initialize bot with handlers
    MangaBot(
        application,
        ALLOWED_USERS,
        KINDLE_EMAIL,
        SENDER_EMAIL,
        SENDER_PASSWORD
    )

    print("Bot started! Press Ctrl+C to exit.")

    # Run the bot
    application.run_polling()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
