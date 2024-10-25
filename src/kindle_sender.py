import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart


class KindleSender:
    """Handles sending files to Kindle devices"""

    def __init__(self, kindle_email: str, sender_email: str, sender_password: str):
        self.kindle_email = kindle_email
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.logger = logging.getLogger(__name__)

    def send_file(self, file_path: str) -> bool:
        """
        Send a file to Kindle device via email
        Returns True if successful, False otherwise
        """
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.kindle_email

            # Don't use Convert for AZW3 files
            msg['Subject'] = "Send" if file_path.endswith('.azw3') else "Convert"

            # Attach the file
            with open(file_path, "rb") as f:
                attachment = MIMEApplication(f.read())
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=os.path.basename(file_path)
                )
                msg.attach(attachment)

            # Connect to Gmail SMTP server using SSL
            self.logger.info(f"Connecting to SMTP server...")
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(self.sender_email, self.sender_password)

            # Send the email
            self.logger.info(f"Sending file {os.path.basename(file_path)} to Kindle...")
            server.send_message(msg)
            server.quit()

            self.logger.info("File sent successfully!")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send file to Kindle: {str(e)}")
            return False
