import logging
import os
from typing import List, Dict

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

from .kindle_sender import KindleSender
from .manga_merger import MangaVolumeMerger


class MangaBot:
    """Telegram bot for processing manga chapters and sending to Kindle"""

    def __init__(self, application, allowed_users: List[int],
                 kindle_email: str, sender_email: str, sender_password: str):
        self.application = application
        self.allowed_users = allowed_users
        self.merger = MangaVolumeMerger()
        self.kindle_sender = KindleSender(kindle_email, sender_email, sender_password)
        self.pending_chapters: Dict[int, List[str]] = {}
        self.logger = logging.getLogger(__name__)

        # Setup handlers
        self.setup_handlers()

    def setup_handlers(self):
        """Setup bot command and message handlers"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("merge", self.merge))
        self.application.add_handler(CommandHandler("clear", self.clear))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            'Welcome to Manga to Kindle bot!\n\n'
            'Send me CBZ manga chapters and I\'ll merge them into volumes '
            'and send them to your Kindle.\n\n'
            'Use /help to see available commands.'
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await update.message.reply_text(
            'Available commands:\n\n'
            '/start - Start the bot\n'
            '/help - Show this help message\n'
            '/merge - Merge pending chapters into volumes and send to Kindle\n'
            '/clear - Clear pending chapters\n'
            '/status - Show number of pending chapters\n\n'
            'Simply send CBZ files to add chapters to the queue.'
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        pending_count = len(self.pending_chapters.get(user_id, []))
        await update.message.reply_text(f"You have {pending_count} pending chapters.")

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear command"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id in self.pending_chapters:
            # Clean up files
            for file_path in self.pending_chapters[user_id]:
                if os.path.exists(file_path):
                    os.remove(file_path)
            self.pending_chapters[user_id] = []
            await update.message.reply_text("Pending chapters cleared!")
        else:
            await update.message.reply_text("No pending chapters to clear.")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle received documents"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        document = update.message.document
        if not document.file_name.lower().endswith('.cbz'):
            await update.message.reply_text("Please send only CBZ files.")
            return

        # Download file
        file = await context.bot.get_file(document.file_id)
        download_path = f"downloads/{document.file_name}"
        os.makedirs("downloads", exist_ok=True)
        await file.download_to_drive(download_path)

        # Store chapter
        if user_id not in self.pending_chapters:
            self.pending_chapters[user_id] = []
        self.pending_chapters[user_id].append(download_path)

        await update.message.reply_text(
            f"Chapter received! Total chapters: {len(self.pending_chapters[user_id])}\n"
            f"Use /merge when you've sent all chapters."
        )

    async def merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /merge command"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id not in self.pending_chapters or not self.pending_chapters[user_id]:
            await update.message.reply_text("No chapters to merge. Send some chapters first!")
            return

        try:
            await update.message.reply_text("Processing chapters...")

            # Group chapters into volumes
            volumes = self.merger.group_chapters_into_volumes(self.pending_chapters[user_id])

            # Process each volume
            for vol_num, chapter_files in volumes.items():
                await update.message.reply_text(f"Creating volume {vol_num}...")
                output_path = f"downloads/volume_{vol_num}.azw3"

                processed_path = self.merger.merge_chapters_to_volume(
                    chapter_files, output_path
                )

                if processed_path and self.kindle_sender.send_file(processed_path):
                    await update.message.reply_text(f"Volume {vol_num} sent to Kindle!")
                else:
                    await update.message.reply_text(f"Failed to process volume {vol_num}")

                # Cleanup
                if processed_path and os.path.exists(processed_path):
                    os.remove(processed_path)

            # Clear pending chapters
            for file_path in self.pending_chapters[user_id]:
                if os.path.exists(file_path):
                    os.remove(file_path)
            self.pending_chapters[user_id] = []

        except Exception as e:
            self.logger.error(f"Error processing volumes: {str(e)}")
            await update.message.reply_text(f"Error processing volumes: {str(e)}")
