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

    async def confirm_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle merge confirmation and process the manga volume"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        if query.data == 'cancel':
            await query.edit_message_text("🚫 Merge cancelled.")
            return ConversationHandler.END

        metadata = self.merge_metadata[user_id]
        manga_title = metadata['title'].replace(' ', '_')
        base_name = os.path.join("downloads", manga_title)

        status_message = await query.edit_message_text(
            "🔄 Processing chapters...\n"
            "Please wait, this may take a few minutes."
        )

        try:
            # Merge chapters
            processed_volumes = self.merger.merge_chapters_to_volume(
                self.pending_chapters[user_id],
                base_name
            )

            if not processed_volumes:
                await status_message.edit_text(
                    "❌ Failed to merge chapters.\n"
                    "Please check if all files are valid manga chapters."
                )
                return ConversationHandler.END

            # Send each volume to Kindle and Telegram
            total_volumes = len(processed_volumes)
            successful_sends_kindle = []
            failed_sends_kindle = []
            successful_sends_telegram = []
            failed_sends_telegram = []

            for i, (pdf_path, chapter_range) in enumerate(processed_volumes, 1):
                await status_message.edit_text(
                    f"📤 Sending volume {chapter_range}...\n"
                    f"({i}/{total_volumes})"
                )

                # Send to Kindle
                kindle_success = self.kindle_sender.send_file(pdf_path)
                if kindle_success:
                    successful_sends_kindle.append(chapter_range)
                else:
                    failed_sends_kindle.append(chapter_range)

                # Send to Telegram
                try:
                    with open(pdf_path, 'rb') as pdf_file:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=pdf_file,
                            filename=f"{manga_title}{chapter_range}.pdf",
                            caption=f"📚 {metadata['title']} {chapter_range}"
                        )
                    successful_sends_telegram.append(chapter_range)
                except Exception as e:
                    self.logger.error(f"Failed to send PDF to Telegram: {e}")
                    failed_sends_telegram.append(chapter_range)

            # Prepare completion message
            status_kindle = "✅" if successful_sends_kindle and not failed_sends_kindle else "⚠️" if successful_sends_kindle else "❌"
            status_telegram = "✅" if successful_sends_telegram and not failed_sends_telegram else "⚠️" if successful_sends_telegram else "❌"

            result_message = (
                f"📱 Telegram Delivery: {status_telegram}\n"
                f"📖 Kindle Delivery: {status_kindle}\n\n"
                f"📚 {metadata['title']}\n"
            )

            if successful_sends_kindle:
                result_message += f"✅ Sent to Kindle: Chapters {', '.join(successful_sends_kindle)}\n"
            if failed_sends_kindle:
                result_message += f"❌ Failed (Kindle): Chapters {', '.join(failed_sends_kindle)}\n"

            if successful_sends_telegram:
                result_message += f"✅ Sent to Telegram: Chapters {', '.join(successful_sends_telegram)}\n"
            if failed_sends_telegram:
                result_message += f"❌ Failed (Telegram): Chapters {', '.join(failed_sends_telegram)}\n"

            result_message += f"\n📧 Kindle: {self.kindle_sender.kindle_email}"

            await status_message.edit_text(result_message)

            # Cleanup files
            try:
                # Clean up processed volumes
                for pdf_path, _ in processed_volumes:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)

                # Clean up original files
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
