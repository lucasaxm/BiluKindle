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
    VOLUME = 2
    CONFIRM = 3

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
                self.VOLUME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.get_volume
                    )
                ],
                self.CONFIRM: [
                    CallbackQueryHandler(self.confirm_merge, pattern='^(confirm|cancel)$')
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_merge)],
            name="merge_conversation",
            persistent=False
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

    async def get_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle manga title input"""
        user_id = update.message.from_user.id
        title = update.message.text.strip()

        if not title:
            await update.message.reply_text("Please enter a valid title.")
            return self.TITLE

        self.merge_metadata[user_id]['title'] = title
        await update.message.reply_text(
            f"Title set to: {title}\n\n"
            f"Please enter the volume number (e.g., '1'):"
        )
        return self.VOLUME

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
        """
        Handle merge confirmation and process the manga volume
        Includes detailed progress updates and error handling
        """
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        if query.data == 'cancel':
            await query.edit_message_text("🚫 Merge cancelled.")
            return ConversationHandler.END

        # Get metadata
        metadata = self.merge_metadata[user_id]

        # Initialize status message
        status_message = await query.edit_message_text(
            "🔄 Starting process...\n\n"
            "This may take a few minutes depending on the number "
            "and size of chapters."
        )

        # Flag to control progress updates
        is_sending_complete = False

        async def update_status(text: str):
            """Helper function to update status message"""
            try:
                if not is_sending_complete:  # Only update if sending isn't complete
                    await status_message.edit_text(text)
            except Exception as e:
                self.logger.error(f"Failed to update status message: {e}")

        try:
            # Validate pending chapters
            if not self.pending_chapters.get(user_id):
                await update_status("❌ Error: No chapters found to process.")
                return ConversationHandler.END

            # Create output filename with manga title and volume
            output_filename = (
                f"{metadata['title']}_Vol_{metadata['volume']}"
                f"_{len(self.pending_chapters[user_id])}_chapters.pdf"
            )
            output_path = os.path.join("downloads", output_filename)

            # Update status with chapter count and processing info
            await update_status(
                f"📚 Processing {len(self.pending_chapters[user_id])} chapters...\n\n"
                f"Title: {metadata['title']}\n"
                f"Volume: {metadata['volume']}\n\n"
                "🔄 Merging chapters..."
            )

            # Merge chapters
            processed_path = self.merger.merge_chapters_to_volume(
                self.pending_chapters[user_id],
                output_path
            )

            if not processed_path:
                await update_status(
                    "❌ Failed to merge chapters.\n\n"
                    "Please check if all files are valid manga chapters."
                )
                return ConversationHandler.END

            # Check if merged file exists and has size
            if not os.path.exists(processed_path) or os.path.getsize(processed_path) == 0:
                await update_status(
                    "❌ Error: Generated file is invalid or empty.\n\n"
                    "Please try again with different chapters."
                )
                return ConversationHandler.END

            # Update status before sending to Kindle
            await update_status(
                f"✅ Chapters merged successfully!\n\n"
                f"📤 Sending to Kindle: {self.kindle_sender.kindle_email}\n"
                f"Please wait..."
            )

            # Create a wrapper for the progress callback that uses asyncio
            async def send_to_kindle():
                def progress_callback(msg: str):
                    # Create a coroutine that we can await
                    async def update_progress():
                        await update_status(
                            f"📤 Sending to Kindle...\n\n"
                            f"Status: {msg}"
                        )

                    # Schedule the coroutine to run
                    context.application.create_task(update_progress())

                return self.kindle_sender.send_file(processed_path, progress_callback)

            # Send to Kindle
            success = await context.application.create_task(send_to_kindle())

            # Set flag to prevent further progress updates
            is_sending_complete = True

            if success:
                final_message = (
                    f"✅ Success! Volume {metadata['volume']} of {metadata['title']}"
                    f" has been sent to your Kindle.\n\n"
                    f"📚 Chapters: {len(self.pending_chapters[user_id])}\n"
                    f"📧 Sent to: {self.kindle_sender.kindle_email}\n\n"
                    f"The book should appear on your Kindle shortly."
                )
            else:
                final_message = (
                    "❌ Failed to send to Kindle.\n\n"
                    "Please check:\n"
                    "1. Your Kindle email address is correct\n"
                    "2. The sender email is approved in your Amazon account\n"
                    "3. Your email server settings are correct\n\n"
                    "Use /help for more information."
                )

            # Final status update
            await status_message.edit_text(final_message)

            # Cleanup files
            try:
                # Clean up merged file
                if processed_path and os.path.exists(processed_path):
                    os.remove(processed_path)

                # Clean up original chapter files
                for file_path in self.pending_chapters[user_id]:
                    if os.path.exists(file_path):
                        os.remove(file_path)

                self.pending_chapters[user_id] = []

            except Exception as e:
                self.logger.error(f"Error during cleanup: {e}")
                # Don't show cleanup errors to user unless it's critical

        except Exception as e:
            error_message = str(e)
            self.logger.error(f"Error processing volume: {error_message}")

            # Provide user-friendly error message
            await update_status(
                f"❌ Error processing volume:\n\n"
                f"{error_message}\n\n"
                f"Please try again or contact support if the issue persists."
            )

        finally:
            # Clear metadata regardless of success/failure
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
