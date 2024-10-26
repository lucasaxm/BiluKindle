# Manga to Kindle Telegram Bot 📚

A Telegram bot that processes manga chapters (CBZ/PDF) and automatically sends them to your Kindle device. Perfect for managing your manga collection and reading on Kindle.

## Features ✨

- Convert CBZ files to Kindle-optimized PDFs
- Smart chapter number detection and ordering
- Automatic volume creation based on chapter ranges
- Direct delivery to Kindle via email
- Telegram-based interface for easy management
- Support for multiple concurrent users
- File size optimization for Kindle/email limits
- Automatic cleanup of processed files
- Progress tracking and detailed status updates

## Prerequisites 🛠️

- Python 3.8+
- Calibre (for ebook-convert command)
- Gmail account (for sending to Kindle)
- Telegram Bot Token
- Kindle email address

### System Dependencies

```bash
# Ubuntu/Debian
sudo apt-get install calibre

# macOS
brew install calibre

# Windows
# Download and install from https://calibre-ebook.com/download
```

## Installation 📥

1. Clone the repository:
```bash
git clone https://github.com/yourusername/manga-kindle-bot.git
cd manga-kindle-bot
```

2. Create and activate virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

3. Install Python dependencies:
```bash
pip install -r requirements.txt
```

4. Copy example environment file and configure:
```bash
cp .env.example .env
```

## Configuration ⚙️

Edit `.env` file with your settings:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USERS=your_telegram_user_id_here
KINDLE_EMAIL=your_kindle_email@kindle.com
SENDER_EMAIL=your_gmail@gmail.com
SENDER_PASSWORD=your_app_specific_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SMTP_USE_SSL=True
```

### Important Setup Steps:

1. Create a Telegram bot via [@BotFather](https://t.me/botfather) and get the token
2. Get your Telegram User ID via [@userinfobot](https://t.me/userinfobot)
3. [Create an app-specific password](https://support.google.com/accounts/answer/185833?hl=en) for your Gmail account
4. Add your sender email to [approved senders in Amazon's Kindle settings](https://www.amazon.com/hz/mycd/myx#/home/settings/payment)

## Usage 📱

1. Start the bot:
```bash
python run_bot.py
```

2. In Telegram, interact with the bot:
- `/start` - Initialize the bot
- `/help` - Show available commands
- Send CBZ/PDF files to add to queue
- `/status` - Check pending chapters
- `/merge` - Process and send chapters to Kindle
- `/clear` - Clear pending queue

### Example Workflow:

1. Send multiple chapter files to the bot
2. Use `/status` to verify received chapters
3. Use `/merge` when ready to process
4. Enter manga title when prompted
5. Confirm the merge operation
6. Wait for processing and delivery
7. Check your Kindle device!

## File Naming 📁

The bot creates files following this format:
```
MangaTitle [1-3].pdf   # For chapters 1-3
MangaTitle [4-6].pdf   # For chapters 4-6
```

## Limitations 📏

- Maximum file size: 23MB (Gmail attachment limit)
- Supported formats: CBZ, PDF
- Requires Calibre for CBZ conversion
- Gmail sending limits apply

## Troubleshooting 🔧

1. **Files not appearing on Kindle:**
    - Check spam folder in Kindle email
    - Verify sender email is approved in Amazon settings
    - Ensure file size is under 23MB

2. **Conversion errors:**
    - Verify Calibre is properly installed
    - Check if `ebook-convert` command works in terminal
    - Ensure CBZ files are valid

3. **Bot not responding:**
    - Verify your user ID is in ALLOWED_USERS
    - Check bot token is correct
    - Ensure bot is running

## Contributing 🤝

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments 🙏

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for the excellent Telegram bot API
- [Calibre](https://calibre-ebook.com/) for ebook conversion capabilities
- All contributors and users of this bot

## Support 💖

If you find this project helpful, please give it a ⭐️ on GitHub!