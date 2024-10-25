import logging
import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class KindleSender:
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

    def send_file(self, file_path: str) -> bool:
        """Send a file to Kindle device via email"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.kindle_email
            msg['Subject'] = "Convert" if file_path.lower().endswith('.cbz') else "Send"

            # Add some helpful text
            body = "This email was sent by your Manga to Kindle bot."
            msg.attach(MIMEText(body, 'plain'))

            # Attach the file
            with open(file_path, "rb") as f:
                attachment = MIMEApplication(f.read())
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=os.path.basename(file_path)
                )
                msg.attach(attachment)

            # Connect to SMTP server
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
            server.send_message(msg)
            server.quit()

            self.logger.info(f"Successfully sent {os.path.basename(file_path)} to Kindle")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send file to Kindle: {str(e)}")
            return False
