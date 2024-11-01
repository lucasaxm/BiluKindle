import asyncio
import logging
from contextlib import asynccontextmanager

from telegram.ext import Application
from telethon import TelegramClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def managed_bot(application: Application, telethon_client: TelegramClient):
    """Context manager to handle proper initialization and cleanup of bot resources"""
    try:
        # Initialize and start both clients
        await application.initialize()
        await application.start()
        await telethon_client.connect()

        yield application, telethon_client
    finally:
        # Ensure proper shutdown
        try:
            if application.updater and application.updater.running:
                await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down application: {e}")

        try:
            await telethon_client.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting Telethon client: {e}")

        # Cleanup any remaining event loop resources
        try:
            pending = asyncio.all_tasks()
            for task in pending:
                if not task.done() and task != asyncio.current_task():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        except Exception as e:
            logger.error(f"Error cleaning up tasks: {e}")
