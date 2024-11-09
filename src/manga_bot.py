import logging
import os
import typing
from typing import List, Dict, Any

from telegram import Update, InputMediaPhoto, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telethon import TelegramClient

import config
from . import manga_merger
from .manga_merger import MangaVolumeMerger


class MangaBot:
    """
    Telegram bot for processing manga chapters and sending to Kindle
    Handles user interactions, file processing, and Kindle delivery
    """

    # Conversation states
    TITLE = 1
    COVER = 2
    CONFIRM = 3
    REMOVE_PAGES = 5

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
        self.last_status_message_id: Dict[int, int] = {}

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
            MessageHandler(filters.PHOTO, self.handle_photo),
            CommandHandler("confirm", self.confirm_merge)
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
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id not in self.pending_chapters or not self.pending_chapters[user_id]:
            await update.message.reply_text("No pending chapters.")
            return

        try:
            if user_id in self.last_status_message_id:
                try:
                    await context.bot.delete_message(chat_id=update.message.chat_id,
                                                     message_id=self.last_status_message_id[user_id])
                except Exception as e:
                    self.logger.error(f"Error deleting previous status message: {e}")

            chapter_info = []
            for file_path in self.pending_chapters[user_id]:
                try:
                    chapter_num = self.merger.extract_chapter_number(file_path)
                    chapter_info.append((chapter_num, file_path))
                except ValueError:
                    continue

            chapter_info.sort()

            if chapter_info:
                if len(chapter_info) == 1:
                    chapters_str = f"Chapter {manga_merger.chapter_number_to_str(chapter_info[0][0])}"
                else:
                    chapters_str = f"Chapters {manga_merger.chapter_number_to_str(chapter_info[0][0])}-{manga_merger.chapter_number_to_str(chapter_info[-1][0])}"
            else:
                chapters_str = "Unknown chapters"

            total_size = sum(os.path.getsize(f) for _, f in chapter_info if os.path.exists(f))
            size_mb = total_size / (1024 * 1024)

            file_list = "\n".join(f"📁 {os.path.basename(file_path)}" for _, file_path in chapter_info)

            cover_photo_path = os.path.join("downloads", "cover.jpg")
            if os.path.exists(cover_photo_path):
                with open(cover_photo_path, 'rb') as photo:
                    title = self.merge_metadata.get(user_id, {}).get('title', 'No title set')
                    pages_to_remove = self.merge_metadata.get(user_id, {}).get('pages_to_remove', [])
                    pages_to_remove_str = ', '.join(
                        os.path.basename(page) for page in pages_to_remove) if pages_to_remove else 'None'
                    message = await update.message.reply_photo(
                        photo=photo,
                        caption=(
                            f"📚 Pending: {len(chapter_info)} files\n"
                            f"📑 {chapters_str}\n\n"
                            f"{file_list}\n\n"
                            f"💾 Total size: {size_mb:.1f}MB\n"
                            f"📖 Title: {title}\n"
                            f"🗑️ Pages to remove: {pages_to_remove_str}\n\n"
                            f"Use /{'confirm to proceed or /cancel to abort' if self.user_states.get(user_id) == self.CONFIRM else 'merge when ready to process or /clear to remove all.'}"
                        ),
                        reply_markup=ReplyKeyboardRemove()
                    )
            else:
                title = self.merge_metadata.get(user_id, {}).get('title', 'No title set')
                pages_to_remove = self.merge_metadata.get(user_id, {}).get('pages_to_remove', [])
                pages_to_remove_str = ', '.join(
                    os.path.basename(page) for page in pages_to_remove) if pages_to_remove else 'None'
                message = await update.message.reply_text(
                    f"📚 Pending: {len(chapter_info)} files\n"
                    f"📑 {chapters_str}\n\n"
                    f"{file_list}\n\n"
                    f"💾 Total size: {size_mb:.1f}MB\n"
                    f"📖 Title: {title}\n"
                    f"🗑️ Pages to remove: {pages_to_remove_str}\n\n"
                    f"Use /{'confirm to proceed or /cancel to abort' if self.user_states.get(user_id) == self.CONFIRM else 'merge when ready to process or /clear to remove all.'}",
                    reply_markup=ReplyKeyboardRemove()
                )

            self.last_status_message_id[user_id] = message.message_id

        except Exception as e:
            self.logger.error(f"Error in status: {e}")
            await update.message.reply_text(
                f"You have {len(self.pending_chapters[user_id])} pending chapters.\n"
                "Use /merge when ready or /clear to remove all."
            )

    async def ask_remove_pages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        first_chapter = self.pending_chapters[user_id][0]
        images = self.merger.extract_first_images(first_chapter, 5)

        image_names = [os.path.basename(image) for image in images]

        self.merge_metadata[user_id]['removable_pages'] = image_names
        self.merge_metadata[user_id]['pages_to_remove'] = []

        keyboard = [[name] for name in image_names] + [["Next"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "Which pages would you like to delete?",
            reply_markup=reply_markup
        )

        self.user_states[user_id] = self.REMOVE_PAGES

    async def handle_remove_pages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        response = update.message.text.strip()

        if response.lower() == 'next':
            self.user_states[user_id] = self.CONFIRM
            await self.status(update, context)
            return

        removable_pages = self.merge_metadata[user_id]['removable_pages']
        pages_to_remove = self.merge_metadata[user_id]['pages_to_remove']

        if response not in removable_pages:
            await update.message.reply_text(
                "Invalid selection. Please choose a valid page number or 'Next' to proceed.")
            return

        pages_to_remove.append(response)

        # Update the list of removable pages
        updated_image_names = "\n".join(
            [f"🗑️ {image}" if image in pages_to_remove else os.path.basename(image) for image in
             removable_pages]
        )
        await update.message.reply_text(
            f"Which pages would you like to delete?\n{updated_image_names}\n\nReply with the file name or 'Next' to proceed."
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle received photos"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        photo = update.message.photo[-1]  # Get the highest resolution photo
        file = await context.bot.get_file(photo.file_id)
        download_path = os.path.join("downloads", "cover.jpg")
        os.makedirs("downloads", exist_ok=True)
        await file.download_to_drive(download_path)

        await self.status(update, context)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle received documents"""
        if update.message.chat_id == int(self.storage_chat_id):
            return

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
        download_path = f"downloads/{document.file_name}"
        os.makedirs("downloads", exist_ok=True)

        status_message = await update.message.reply_text(f"🔄 Downloading {document.file_name}...\n0%.")

        def progress_callback(current, total):
            progress = (current / total) * 100
            progress_rounded = int(progress // 5) * 5  # Round down to the nearest multiple of 5%

            if not hasattr(progress_callback, 'last_progress'):
                progress_callback.last_progress = 0

            if progress_rounded > progress_callback.last_progress:
                progress_text = f"🔄 Downloading {document.file_name}...\n{progress_rounded}%."
                context.application.create_task(status_message.edit_text(progress_text))
                progress_callback.last_progress = progress_rounded

        try:
            # Try downloading using python-telegram-bot
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive(download_path)
        except Exception as e:
            if 'File is too big' in str(e):
                # Forward the document to the storage chat
                forwarded_message = await update.message.forward(chat_id=int(self.storage_chat_id))

                # Use Telethon to download the file from the storage chat
                message_id = forwarded_message.message_id
                storage_chat_id = int(self.storage_chat_id)

                def telethon_progress_callback(downloaded, total_bytes):
                    progress = (downloaded / total_bytes) * 100
                    progress_rounded = int(progress // 5) * 5

                    if not hasattr(telethon_progress_callback, 'last_progress'):
                        telethon_progress_callback.last_progress = 0

                    if progress_rounded > telethon_progress_callback.last_progress:
                        progress_text = f"🔄 Downloading {document.file_name}...\n{progress_rounded}%."
                        context.application.create_task(status_message.edit_text(progress_text))
                        telethon_progress_callback.last_progress = progress_rounded

                message = await self.telethon_client.get_messages(storage_chat_id, ids=message_id)
                await self.telethon_client.download_media(
                    message=message,
                    file=download_path,
                    progress_callback=telethon_progress_callback
                )
            else:
                await status_message.edit_text(f"❌ Error downloading file: {str(e)}")
                return

        # Store chapter
        if user_id not in self.pending_chapters:
            self.pending_chapters[user_id] = []
        self.pending_chapters[user_id].append(download_path)

        await status_message.delete()
        await self.status(update, context)

    async def send_large_file(self, file_path: str,
                              progress_callback: typing.Optional[typing.Callable[[int, int], None]] = None) -> str:
        """
        Send a large file using Telethon first to storage chat, then forward to user

        Args:
            file_path: Path to the file to send
            progress_callback: A callback function accepting two parameters: (sent bytes, total)

        Returns:
            str: file_id if successful, empty string otherwise
        """
        try:
            # First upload to storage chat using Telethon
            self.logger.info(f"Uploading file to storage chat: {file_path}")
            file_handle = await self.telethon_client.upload_file(
                file=file_path,
                part_size_kb=512,
                progress_callback=progress_callback
            )
            message = await self.telethon_client.send_file(
                int(self.storage_chat_id),
                file_handle,
                force_document=True
            )

            # Get the message ID from the uploaded message
            if message and message.id:
                message_id = message.id

                # Use the official bot API to get the file ID
                storage_chat_id = int(self.storage_chat_id)
                bot_message = await self.application.bot.forward_message(
                    chat_id=storage_chat_id,
                    from_chat_id=storage_chat_id,
                    message_id=message_id
                )

                if bot_message and bot_message.document:
                    return bot_message.document.file_id
                else:
                    self.logger.error("Failed to get file_id from forwarded message")
                    return ""
            else:
                self.logger.error("Failed to get message ID from uploaded message")
                return ""

        except Exception as e:
            self.logger.error(f"Error sending large file: {str(e)}")
            return ""

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
        elif state == self.COVER:
            await self.handle_cover_selection(update, context)
        elif state == self.REMOVE_PAGES:
            await self.handle_remove_pages(update, context)

    def get_chapter_range(self, files: List[str]) -> str:
        """Get the chapter range string from the files"""
        try:
            chapter_numbers = []
            for file in files:
                chapter_num = self.merger.extract_chapter_number(file)
                chapter_numbers.append(chapter_num)

            chapter_numbers.sort()

            if len(chapter_numbers) == 1:
                return manga_merger.chapter_number_to_str(chapter_numbers[0])
            else:
                return f"[{manga_merger.chapter_number_to_str(chapter_numbers[0])}-{manga_merger.chapter_number_to_str(chapter_numbers[-1])}]"
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

        # Check if cover is set
        cover_photo_path = os.path.join("downloads", "cover.jpg")
        if not os.path.exists(cover_photo_path):
            self.user_states[user_id] = self.COVER
            await self.send_cover_options(update, context)
        else:
            await self.ask_remove_pages(update, context)

    async def send_cover_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        first_chapter = self.pending_chapters[user_id][0]
        images = self.merger.extract_first_images(first_chapter, 5)

        media_group = [InputMediaPhoto(open(image, 'rb')) for image in images]
        await context.bot.send_media_group(chat_id=user_id, media=media_group)

        image_names = [os.path.basename(image) for image in images]
        keyboard = [[name] for name in image_names]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            "Which page should be the cover?",
            reply_markup=reply_markup
        )

    async def handle_cover_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        selected_image = update.message.text.strip()

        first_chapter = self.pending_chapters[user_id][0]
        images = self.merger.extract_first_images(first_chapter, 5)
        image_names = [os.path.basename(image) for image in images]

        if selected_image not in image_names:
            await update.message.reply_text("Invalid selection. Please choose a valid page number.")
            return

        selected_image_path = images[image_names.index(selected_image)]
        cover_photo_path = os.path.join("downloads", "cover.jpg")
        os.rename(selected_image_path, cover_photo_path)

        # Clean up extracted images
        for image in images:
            if os.path.exists(image):
                os.remove(image)

        await self.ask_remove_pages(update, context)

    async def confirm_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id

        if user_id not in self.merge_metadata:
            await update.message.reply_text("No merge operation to confirm.")
            return

        metadata = self.merge_metadata[user_id]
        manga_title = metadata['title']
        pages_to_remove = metadata.get('pages_to_remove', [])

        status_message = await update.message.reply_text(
            "🔄 Processing chapters...\nPlease wait, this may take a few minutes."
        )

        def progress_callback(sent_bytes, total_bytes):
            progress = (sent_bytes / total_bytes) * 100
            progress_rounded = int(progress // 5) * 5  # Round down to the nearest multiple of 5%

            # Initialize last_progress attribute if it doesn't exist
            if not hasattr(progress_callback, 'last_progress'):
                progress_callback.last_progress = 0  # Initialize last_progress

            # Only update if progress has increased by at least 5%
            if progress_rounded > progress_callback.last_progress:
                progress_text = f"📤 Uploading: {progress_rounded:.2f}%"

                # Edit the message
                context.application.create_task(status_message.edit_text(progress_text))

                # Update last_progress
                progress_callback.last_progress = progress_rounded

        try:
            processed_volumes = self.merger.merge_chapters_to_volume(
                self.pending_chapters[user_id], manga_title, pages_to_remove=pages_to_remove
            )

            if not processed_volumes:
                await status_message.edit_text(
                    "❌ Failed to merge chapters.\nPlease check if all files are valid manga chapters."
                )
                return

            total_volumes = len(processed_volumes)
            successful_sends = []
            failed_sends = []

            for i, (file_path, chapter_range) in enumerate(processed_volumes, 1):
                await status_message.edit_text(f"📤 Sending volume {chapter_range}...\n({i}/{total_volumes})")
                caption = f"📚 {metadata['title']} {chapter_range}"
                file_id = await self.send_large_file(file_path, progress_callback=progress_callback)

                if file_id:
                    await self.application.bot.send_document(
                        chat_id=user_id,
                        document=file_id,
                        caption=caption
                    )
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

            cover_photo_path = os.path.join("downloads", "cover.jpg")
            if os.path.exists(cover_photo_path):
                os.remove(cover_photo_path)

            self.pending_chapters[user_id] = []

        except Exception as e:
            self.logger.error(f"Error processing chapters: {e}")
            await status_message.edit_text(f"❌ Error processing chapters: {str(e)}\nPlease try again.")

        finally:
            del self.user_states[user_id]
            if user_id in self.merge_metadata:
                del self.merge_metadata[user_id]
            if user_id in self.last_status_message_id:
                del self.last_status_message_id[user_id]

    async def cancel_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.message.from_user.id
        if user_id in self.merge_metadata:
            del self.merge_metadata[user_id]
        if user_id in self.user_states:
            del self.user_states[user_id]
        if user_id in self.last_status_message_id:
            del self.last_status_message_id[user_id]

        await update.message.reply_text("Merge cancelled.\nIf you want to start from scratch send /clear")

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /clear command"""
        user_id = update.message.from_user.id
        if user_id not in self.allowed_users:
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        if user_id in self.pending_chapters:
            # Clean up files
            for root, dirs, files in os.walk("downloads", topdown=False):
                for file in files:
                    if file != ".gitkeep":
                        os.remove(os.path.join(root, file))
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
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
