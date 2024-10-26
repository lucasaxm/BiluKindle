import logging
import os
from typing import List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)

import config
from .kindle_sender import KindleSender
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
            allowed_users: List[int],
            kindle_email: str,
            sender_email: str,
            sender_password: str
    ):
        """
        Initialize the bot with necessary configurations and handlers

        Args:
            application: Telegram application instance
            allowed_users: List of authorized Telegram user IDs
            kindle_email: Destination Kindle email address
            sender_email: Gmail address for sending files
            sender_password: Gmail app-specific password
        """
        self.application = application
        self.allowed_users = allowed_users
        self.merger = MangaVolumeMerger()
        self.kindle_sender = KindleSender(
            kindle_email,
            sender_email,
            sender_password,
            config.SMTP_SERVER,
            config.SMTP_PORT,
            config.SMTP_USE_SSL
        )

        # Storage for user data
        self.pending_chapters: Dict[int, List[str]] = {}
        self.merge_metadata: Dict[int, Dict[str, Any]] = {}

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Initialize handlers
        self.setup_handlers()

    def setup_handlers(self) -> None:
        """Setup all bot command and message handlers"""
        # Create conversation handler for merge command
        merge_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('merge', self.merge_start)],
            states={
                self.TITLE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.get_title
                    )
                ],
                self.CONFIRM: [
                    CallbackQueryHandler(self.confirm_merge, pattern='^(confirm|cancel)$')
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_merge)],
            name="merge_conversation"
        )

        # Define all handlers
        handlers = [
            merge_conv_handler,
            CommandHandler("start", self.start),
            CommandHandler("help", self.help),
            CommandHandler("clear", self.clear),
            CommandHandler("status", self.status),
            MessageHandler(
                filters.Document.ALL & ~filters.COMMAND,
                self.handle_document
            ),
        ]

        # Register all handlers
        for handler in handlers:
            self.application.add_handler(handler)

        # Add error handler
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
        """Handle the /status command"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        pending_count = len(self.pending_chapters.get(user_id, []))
        await update.message.reply_text(f"You have {pending_count} pending chapters.")

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

    async def merge_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the merge conversation"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return ConversationHandler.END

        if user_id not in self.pending_chapters or not self.pending_chapters[user_id]:
            await update.message.reply_text("No chapters to merge. Send some chapters first!")
            return ConversationHandler.END

        # Initialize merge metadata for this user
        self.merge_metadata[user_id] = {
            'title': None,
            'volume': None
        }

        await update.message.reply_text(
            "Please enter the manga title (e.g., 'One Piece'):"
        )
        return self.TITLE

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

    async def get_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle manga title input"""
        user_id = update.message.from_user.id
        title = update.message.text.strip()

        if not title:
            await update.message.reply_text("Please enter a valid title.")
            return self.TITLE

        self.merge_metadata[user_id] = {'title': title}

        # Get chapter range
        chapter_range = self.get_chapter_range(self.pending_chapters[user_id])

        keyboard = [[
            InlineKeyboardButton("✅ Confirm", callback_data='confirm'),
            InlineKeyboardButton("❌ Cancel", callback_data='cancel')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Please confirm the following:\n\n"
            f"Manga: {title}\n"
            f"Chapters: {chapter_range}\n"
            f"Files to merge: {len(self.pending_chapters[user_id])}\n\n"
            f"Output will be: {title} {chapter_range}.pdf\n\n"
            f"Is this correct?",
            reply_markup=reply_markup
        )
        return self.CONFIRM

    async def get_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle volume number input"""
        user_id = update.message.from_user.id
        try:
            volume = int(update.message.text.strip())
            if volume <= 0:
                raise ValueError("Volume must be positive")
        except ValueError:
            await update.message.reply_text("Please enter a valid positive number.")
            return self.VOLUME

        self.merge_metadata[user_id]['volume'] = volume

        keyboard = [[
            InlineKeyboardButton("✅ Confirm", callback_data='confirm'),
            InlineKeyboardButton("❌ Cancel", callback_data='cancel')
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Please confirm the following:\n\n"
            f"Manga: {self.merge_metadata[user_id]['title']}\n"
            f"Volume: {volume}\n"
            f"Chapters to merge: {len(self.pending_chapters[user_id])}\n\n"
            f"Is this correct?",
            reply_markup=reply_markup
        )
        return self.CONFIRM

    async def confirm_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle merge confirmation and process the manga volume"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        if query.data == 'cancel':
            await query.edit_message_text("🚫 Merge cancelled.")
            return ConversationHandler.END

        # Get metadata
        metadata = self.merge_metadata[user_id]
        chapter_range = self.get_chapter_range(self.pending_chapters[user_id])

        # Initialize status message
        status_message = await query.edit_message_text(
            "🔄 Processing chapters...\n"
            "Please wait, this may take a few minutes."
        )

        try:
            # Create output filename
            output_filename = f"{metadata['title']} {chapter_range}.pdf"
            output_path = os.path.join("downloads", output_filename)

            # Merge chapters
            processed_path = self.merger.merge_chapters_to_volume(
                self.pending_chapters[user_id],
                output_path
            )

            if not processed_path or not os.path.exists(processed_path):
                await status_message.edit_text(
                    "❌ Failed to merge chapters.\n"
                    "Please check if all files are valid manga chapters."
                )
                return ConversationHandler.END

            await status_message.edit_text(
                "📤 Sending to Kindle...\n"
                "Please wait..."
            )

            # Send to Kindle
            success = self.kindle_sender.send_file(processed_path)

            if success:
                await status_message.edit_text(
                    f"✅ Success! {metadata['title']} {chapter_range}"
                    f" has been sent to your Kindle.\n\n"
                    f"📚 Chapters merged: {len(self.pending_chapters[user_id])}\n"
                    f"📧 Sent to: {self.kindle_sender.kindle_email}"
                )
            else:
                await status_message.edit_text(
                    "❌ Failed to send to Kindle.\n\n"
                    "Please check:\n"
                    "1. Your Kindle email address is correct\n"
                    "2. The sender email is approved in your Amazon account\n"
                    "3. Your email server settings are correct"
                )

            # Cleanup files
            try:
                if processed_path and os.path.exists(processed_path):
                    os.remove(processed_path)
                for file_path in self.pending_chapters[user_id]:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                self.pending_chapters[user_id] = []
            except Exception as e:
                self.logger.error(f"Error during cleanup: {e}")

        except Exception as e:
            self.logger.error(f"Error processing chapters: {e}")
            await status_message.edit_text(
                f"❌ Error processing chapters: {str(e)}\n"
                f"Please try again."
            )

        finally:
            if user_id in self.merge_metadata:
                del self.merge_metadata[user_id]

        return ConversationHandler.END

    async def cancel_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the merge conversation"""
        user_id = update.message.from_user.id
        if user_id in self.merge_metadata:
            del self.merge_metadata[user_id]

        await update.message.reply_text("Merge cancelled.")
        return ConversationHandler.END

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the bot"""
        self.logger.error(f"Exception while handling an update: {context.error}")

        # Send message to user
        error_message = "Sorry, an error occurred while processing your request."
        if update and update.effective_message:
            await update.effective_message.reply_text(error_message)
