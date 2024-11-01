"""
Manga to Kindle Converter Bot
A Telegram bot that processes manga chapters and sends them to Kindle
"""

import logging
import os

# Import main classes
from .context_managers import managed_bot
from .kindle_sender import KindleSender
from .manga_bot import MangaBot
from .manga_merger import MangaVolumeMerger

# Version info
__version__ = '1.0.1'

# Setup package-level logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Disable noisy loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('telethon.crypto.aes').setLevel(logging.INFO)

# Setup basic logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def setup_environment() -> None:
    """Setup required directories and logging"""
    os.makedirs('downloads', exist_ok=True)


# Export public interface
__all__ = [
    'MangaBot',
    'MangaVolumeMerger',
    'managed_bot',
    'setup_environment',
    '__version__'
]

# Package initialization
setup_environment()
