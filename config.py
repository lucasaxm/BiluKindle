import os
from typing import List, Dict
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ALLOWED_USERS = [int(id) for id in os.getenv('ALLOWED_USERS', '').split(',') if id]

# Kindle Configuration
KINDLE_EMAIL = os.getenv('KINDLE_EMAIL', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', '')
SENDER_PASSWORD = os.getenv('SENDER_PASSWORD', '')
SMTP_SERVER = os.getenv('SMTP_SERVER', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USE_SSL = os.getenv('SMTP_USE_SSL', 'True').lower() == 'true'
# Processing Configuration
CHAPTERS_PER_VOLUME = 10


# Validation
def validate_config() -> Dict[str, List[str]]:
    errors = {
        'missing': [],
        'invalid': []
    }

    # Check required fields
    required_fields = [
        ('TELEGRAM_BOT_TOKEN', TELEGRAM_BOT_TOKEN),
        ('ALLOWED_USERS', ALLOWED_USERS),
        ('KINDLE_EMAIL', KINDLE_EMAIL),
        ('SENDER_EMAIL', SENDER_EMAIL),
        ('SENDER_PASSWORD', SENDER_PASSWORD)
    ]

    for field_name, field_value in required_fields:
        if not field_value:
            errors['missing'].append(field_name)

    # Validate email formats
    import re
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    if KINDLE_EMAIL and not email_pattern.match(KINDLE_EMAIL):
        errors['invalid'].append('KINDLE_EMAIL')
    if SENDER_EMAIL and not email_pattern.match(SENDER_EMAIL):
        errors['invalid'].append('SENDER_EMAIL')

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
