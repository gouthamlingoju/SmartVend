import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import asyncio
from config import SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL

def _send_email_sync(subject: str, body: str, receiver: str = None):
    """Synchronous function to send email via SMTP."""
    sender = SENDER_EMAIL
    password = SENDER_PASSWORD
    to_email = receiver or RECEIVER_EMAIL
    smtp_server = SMTP_SERVER
    smtp_port = int(SMTP_PORT) if SMTP_PORT else 587

    if not all([sender, password, to_email, smtp_server, smtp_port]):
        print(f"Skipping email '{subject}' - SMTP credentials are not fully configured.")
        return

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print(f"Email '{subject}' sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send email '{subject}': {e}")


async def send_email_async(subject: str, body: str, receiver: str = None):
    """
    Asynchronously sends an email by offloading the synchronous SMTP logic to a background thread.
    Useful for BackgroundTasks or non-blocking async routes.
    """
    await asyncio.to_thread(_send_email_sync, subject, body, receiver)
