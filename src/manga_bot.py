import logging
import os
from typing import List, Dict, Any

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telethon import TelegramClient

import config
from .manga_merger import MangaVolumeMerger


class MangaBot:
    """
    Telegram bot for processing manga chapters and sending to Kindle
    Handles user interactions, file processing, and Kindle delivery
    """

    # Conversation states
    TITLE = 1
    CONFIRM = 2

    def __init__(
            self,
            application: Application,
            telethon_client: TelegramClient,
            allowed_users: List[int],
    ):
        """
        Initialize the bot with necessary configurations and handlers

        Args:
            application: Telegram application instance
            telethon_client: Telethon client for handling large files
            allowed_users: List of authorized Telegram user IDs
        """
        self.application = application
        self.telethon_client = telethon_client
        self.allowed_users = allowed_users
        self.merger = MangaVolumeMerger()
        self.storage_chat_id = config.TELEGRAM_FILE_STORAGE_CHAT_ID

        # Storage for user data
        self.pending_chapters: Dict[int, List[str]] = {}
        self.merge_metadata: Dict[int, Dict[str, Any]] = {}
        self.user_states: Dict[int, int] = {}

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Initialize handlers
        self.setup_handlers()

    def setup_handlers(self) -> None:
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("help", self.help),
            CommandHandler("clear", self.clear),
            CommandHandler("status", self.status),
            CommandHandler("merge", self.merge_start),
            CommandHandler("cancel", self.cancel_merge),
            MessageHandler(filters.Document.ALL & ~filters.COMMAND, self.handle_document),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text),
            CommandHandler("confirm", self.confirm_merge)  # Updated line
        ]

        for handler in handlers:
            self.application.add_handler(handler)

        self.application.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command"""
        await update.message.reply_text(
            'Welcome to Manga to Kindle bot!\n\n'
            'Send me PDF or CBZ manga chapters and I\'ll merge them into volumes '
            'and send them to your Kindle.\n\n'
            'Use /help to see available commands.'
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command"""
        await update.message.reply_text(
            'Available commands:\n\n'
            '/start - Start the bot\n'
            '/help - Show this help message\n'
            '/merge - Start merging chapters (will ask for title and volume number)\n'
            '/clear - Clear pending chapters\n'
            '/status - Show number of pending chapters\n\n'
            'Simply send PDF or CBZ files to add chapters to the queue.\n'
            'When ready, use /merge and follow the prompts to create a volume.'
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /status command with enhanced information"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id not in self.pending_chapters or not self.pending_chapters[user_id]:
            await update.message.reply_text("No pending chapters.")
            return

        try:
            # Get chapter numbers for better information
            chapter_info = []
            for file_path in self.pending_chapters[user_id]:
                try:
                    chapter_num = self.merger.extract_chapter_number(file_path)
                    chapter_info.append(chapter_num)
                except ValueError:
                    continue

            chapter_info.sort()

            if chapter_info:
                if len(chapter_info) == 1:
                    chapters_str = f"Chapter {chapter_info[0]}"
                else:
                    chapters_str = f"Chapters {chapter_info[0]}-{chapter_info[-1]}"
            else:
                chapters_str = "Unknown chapters"

            total_size = sum(
                os.path.getsize(f) for f in self.pending_chapters[user_id]
                if os.path.exists(f)
            )
            size_mb = total_size / (1024 * 1024)

            await update.message.reply_text(
                f"📚 Pending: {len(self.pending_chapters[user_id])} files\n"
                f"📑 {chapters_str}\n"
                f"💾 Total size: {size_mb:.1f}MB\n\n"
                f"Use /merge when ready to process or /clear to remove all."
            )

        except Exception as e:
            self.logger.error(f"Error in status: {e}")
            await update.message.reply_text(
                f"You have {len(self.pending_chapters[user_id])} pending chapters.\n"
                "Use /merge when ready or /clear to remove all."
            )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle received documents"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        document = update.message.document
        file_name = document.file_name.lower()
        if not (file_name.endswith('.pdf') or file_name.endswith('.cbz')):
            await update.message.reply_text("Please send only PDF or CBZ files.")
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

    async def send_large_file(self, file_path: str, user_id: int, caption: str) -> bool:
        """
        Send a large file using Telethon first to storage chat, then forward to user

        Args:
            file_path: Path to the file to send
            user_id: Telegram user ID to send the file to
            caption: Caption for the file

        Returns:
            bool: True if successful, False otherwise
        """

        try:
            # First upload to storage chat using Telethon
            self.logger.info(f"Uploading file to storage chat: {file_path}")
            message = await self.telethon_client.send_file(
                int(self.storage_chat_id),
                file_path,
                caption=caption,
                force_document=True
            )

            # Get the message ID from the uploaded message
            if message and message.id:
                message_id = message.id

                # Use the official bot API to get the file ID
                storage_chat_id = int(self.storage_chat_id)
                bot_message = await self.application.bot.forward_message(
                    chat_id=user_id,
                    from_chat_id=storage_chat_id,
                    message_id=message_id
                )

                if bot_message and bot_message.document:
                    file_id = bot_message.document.file_id

                    # Now send to user using the bot API with the file_id
                    await self.application.bot.send_document(
                        chat_id=user_id,
                        document=file_id,
                        caption=caption
                    )
                    return True
                else:
                    self.logger.error("Failed to get file_id from forwarded message")
                    return False
            else:
                self.logger.error("Failed to get message ID from uploaded message")
                return False

        except Exception as e:
            self.logger.error(f"Error sending large file: {str(e)}")
            return False

    async def merge_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id not in self.pending_chapters or not self.pending_chapters[user_id]:
            await update.message.reply_text("No chapters to merge. Send some chapters first!")
            return

        self.merge_metadata[user_id] = {'title': None}
        self.user_states[user_id] = self.TITLE

        await update.message.reply_text("Please enter the manga title (e.g., 'One Piece'):")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id not in self.user_states:
            return

        state = self.user_states[user_id]

        if state == self.TITLE:
            await self.get_title(update, context)

    def get_chapter_range(self, files: List[str]) -> str:
        """Get the chapter range string from the files"""
        try:
            chapter_numbers = []
            for file in files:
                chapter_num = self.merger.extract_chapter_number(file)
                chapter_numbers.append(chapter_num)

            chapter_numbers.sort()

            if len(chapter_numbers) == 1:
                return f"[{chapter_numbers[0]}]"
            else:
                return f"[{chapter_numbers[0]}-{chapter_numbers[-1]}]"
        except Exception as e:
            self.logger.error(f"Error getting chapter range: {e}")
            return "[unknown]"

    async def get_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        title = update.message.text.strip()

        if not title:
            await update.message.reply_text("Please enter a valid title.")
            return

        self.merge_metadata[user_id]['title'] = title
        self.user_states[user_id] = self.CONFIRM

        chapter_range = self.get_chapter_range(self.pending_chapters[user_id])

        await update.message.reply_text(
            f"Please confirm the following:\n\n"
            f"Manga: {title}\n"
            f"Chapters: {chapter_range}\n"
            f"Files to merge: {len(self.pending_chapters[user_id])}\n\n"
            f"Output will be: {title} {chapter_range}.epub\n\n"
            f"Is this correct?"
            f"Use /confirm to proceed or /cancel to abort."
        )

    async def confirm_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id

        if user_id not in self.merge_metadata:
            await update.message.reply_text("No merge operation to confirm.")
            return

        metadata = self.merge_metadata[user_id]
        manga_title = metadata['title']
        base_name = os.path.join("downloads", manga_title)

        status_message = await update.message.reply_text(
            "🔄 Processing chapters...\nPlease wait, this may take a few minutes.")

        try:
            processed_volumes = self.merger.merge_chapters_to_volume(self.pending_chapters[user_id], base_name)

            if not processed_volumes:
                await status_message.edit_text(
                    "❌ Failed to merge chapters.\nPlease check if all files are valid manga chapters.")
                return

            total_volumes = len(processed_volumes)
            successful_sends = []
            failed_sends = []

            for i, (file_path, chapter_range) in enumerate(processed_volumes, 1):
                await status_message.edit_text(f"📤 Sending volume {chapter_range}...\n({i}/{total_volumes})")
                caption = f"📚 {metadata['title']} {chapter_range}"
                success = await self.send_large_file(file_path, user_id, caption)

                if success:
                    successful_sends.append(chapter_range)
                else:
                    failed_sends.append(chapter_range)

            status = "✅" if successful_sends and not failed_sends else "⚠️" if successful_sends else "❌"
            result_message = f"📱 File Delivery: {status}\n📚 {metadata['title']}\n"

            if successful_sends:
                result_message += f"✅ Sent successfully: Chapters {', '.join(successful_sends)}\n"
            if failed_sends:
                result_message += f"❌ Failed to send: Chapters {', '.join(failed_sends)}\n"

            await status_message.edit_text(result_message)

            for file_path, _ in processed_volumes:
                if os.path.exists(file_path):
                    os.remove(file_path)

            for file_path in self.pending_chapters[user_id]:
                if os.path.exists(file_path):
                    os.remove(file_path)

            self.pending_chapters[user_id] = []

            if os.path.exists(base_name):
                os.rmdir(base_name)

        except Exception as e:
            self.logger.error(f"Error processing chapters: {e}")
            await status_message.edit_text(f"❌ Error processing chapters: {str(e)}\nPlease try again.")

        finally:
            del self.user_states[user_id]
            if user_id in self.merge_metadata:
                del self.merge_metadata[user_id]

    async def cancel_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        if user_id in self.merge_metadata:
            del self.merge_metadata[user_id]
        if user_id in self.user_states:
            del self.user_states[user_id]

        await update.message.reply_text("Merge cancelled.\nIf you want to start from scratch send /clear")

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /clear command"""
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

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the bot"""
        self.logger.error(f"Exception while handling an update: {context.error}")

        # Send message to user
        error_message = "Sorry, an error occurred while processing your request."
        if update and update.effective_message:
            await update.effective_message.reply_text(error_message)
