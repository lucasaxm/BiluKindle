"""
Manga to Kindle Converter Bot
A Telegram bot that processes manga chapters and sends them to Kindle
"""

import logging
import os
from typing import Optional

# Version info
__version__ = '1.0.0'

# Setup package-level logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import main classes
from .manga_merger import MangaVolumeMerger
from .manga_bot import MangaBot
from .kindle_sender import KindleSender


# Convenience functions
def setup_environment() -> None:
    """Setup required directories and logging"""
    # Create required directories
    os.makedirs('downloads', exist_ok=True)

    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )


def create_bot(token: str, allowed_users: list) -> Optional[MangaBot]:
    """
    Factory method to create a configured bot instance
    Returns None if configuration is invalid
    """
    try:
        return MangaBot(token, allowed_users)
    except Exception as e:
        logger.error(f"Failed to create bot: {str(e)}")
        return None


# Export public interface
__all__ = [
    'MangaBot',
    'MangaVolumeMerger',
    'KindleSender',
    'setup_environment',
    'create_bot',
    '__version__'
]

# Package initialization
setup_environment()
