import logging
import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple


class EmailError(Exception):
    """Custom exception for email-related errors"""
    pass


class KindleSender:
    """Handles sending files to Kindle devices"""

    def __init__(
            self,
            kindle_email: str,
            sender_email: str,
            sender_password: str,
            smtp_server: str,
            smtp_port: int,
            use_ssl: bool = True
    ):
        self.kindle_email = kindle_email
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.use_ssl = use_ssl
        self.logger = logging.getLogger(__name__)

    def _create_email_message(self, file_path: str) -> Tuple[MIMEMultipart, str]:
        """
        Create the email message with the file attachment
        Returns tuple of (message, file_size_mb)
        """
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.kindle_email
            msg['Subject'] = "Convert" if file_path.lower().endswith('.cbz') else "Send"

            # Add some helpful text
            body = (
                "This email was sent by your Manga to Kindle bot.\n"
                "If you don't receive the file on your Kindle, please:\n"
                "1. Check if the sender email is in your approved senders list\n"
                "2. Verify your Kindle email address\n"
                "3. Check your Amazon content library\n"
            )
            msg.attach(MIMEText(body, 'plain'))

            # Get file size before attaching
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

            # Attach the file
            with open(file_path, "rb") as f:
                attachment = MIMEApplication(f.read())
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=os.path.basename(file_path)
                )
                msg.attach(attachment)

            return msg, file_size_mb

        except FileNotFoundError:
            raise EmailError(f"File not found: {file_path}")
        except Exception as e:
            raise EmailError(f"Error creating email message: {str(e)}")

    def _connect_to_smtp(self) -> Optional[smtplib.SMTP]:
        """
        Establish connection to SMTP server
        Returns SMTP connection object or raises EmailError
        """
        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(
                    self.smtp_server,
                    self.smtp_port,
                    context=context
                )
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()

            server.login(self.sender_email, self.sender_password)
            return server

        except smtplib.SMTPAuthenticationError:
            raise EmailError("Failed to authenticate with email server. Check your credentials.")
        except smtplib.SMTPConnectError:
            raise EmailError(f"Failed to connect to SMTP server {self.smtp_server}")
        except Exception as e:
            raise EmailError(f"SMTP connection error: {str(e)}")

    def send_file(self, file_path: str, progress_callback=None) -> bool:
        """
        Send a file to Kindle device via email
        Args:
            file_path: Path to the file to send
            progress_callback: Optional callback function to report progress
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if progress_callback:
                progress_callback("Creating email message...")

            msg, file_size_mb = self._create_email_message(file_path)

            # Check file size
            if file_size_mb > 50:
                raise EmailError(
                    f"File size ({file_size_mb:.1f}MB) exceeds Kindle's 50MB limit"
                )

            if progress_callback:
                progress_callback("Connecting to email server...")

            server = self._connect_to_smtp()

            if progress_callback:
                progress_callback(f"Sending file ({file_size_mb:.1f}MB)...")

            server.send_message(msg)
            server.quit()

            if progress_callback:
                progress_callback("File sent successfully!")

            self.logger.info(f"Successfully sent {os.path.basename(file_path)} to Kindle")
            return True

        except EmailError as e:
            error_msg = str(e)
            self.logger.error(f"Email error: {error_msg}")
            if progress_callback:
                progress_callback(f"Error: {error_msg}")
            return False

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error(error_msg)
            if progress_callback:
                progress_callback(f"Error: {error_msg}")
            return False
