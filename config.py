import os
from typing import List, Dict

from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ALLOWED_USERS = [int(id) for id in os.getenv('ALLOWED_USERS', '').split(',') if id]
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID', '')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH', '')
TELEGRAM_FILE_STORAGE_CHAT_ID = os.getenv('TELEGRAM_FILE_STORAGE_CHAT_ID', '')
TELEGRAM_PHONE = os.getenv('TELEGRAM_PHONE', '')  # Format: +1234567890
TELETHON_SESSION_STRING = os.getenv('TELETHON_SESSION_STRING', '')  # Will be generated first time


# Validation
def validate_config() -> Dict[str, List[str]]:
    errors = {
        'missing': [],
        'invalid': []
    }

    # Check required fields
    required_fields = [
        ('TELEGRAM_BOT_TOKEN', TELEGRAM_BOT_TOKEN),
        ('TELEGRAM_API_ID', TELEGRAM_API_ID),
        ('TELEGRAM_API_HASH', TELEGRAM_API_HASH),
        ('TELEGRAM_PHONE', TELEGRAM_PHONE),  # New required field
        ('ALLOWED_USERS', ALLOWED_USERS)
    ]

    for field_name, field_value in required_fields:
        if not field_value:
            errors['missing'].append(field_name)

    # Validate phone format
    import re
    phone_pattern = re.compile(r'^\+[1-9]\d{1,14}$')
    if TELEGRAM_PHONE and not phone_pattern.match(TELEGRAM_PHONE):
        errors['invalid'].append('TELEGRAM_PHONE')

    return errors


def print_config_status():
    """Print configuration status and any errors"""
    errors = validate_config()

    if not any(errors.values()):
        print("Configuration valid!")
        return True

    if errors['missing']:
        print("Missing required configuration:")
        for field in errors['missing']:
            print(f"- {field}")

    if errors['invalid']:
        print("Invalid configuration:")
        for field in errors['invalid']:
            print(f"- {field}")

    return False


# Environment setup
def setup_env():
    """Create necessary directories"""
    os.makedirs('downloads', exist_ok=True)
