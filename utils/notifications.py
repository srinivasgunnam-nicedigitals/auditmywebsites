import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings

def send_low_credit_email(user_email: str, current_credits: int):
    """
    Sends an automated email to the user when their credits are low (<= 50).
    """
    if not settings.smtp_user or not settings.smtp_password:
        logging.error("SMTP credentials not configured in settings. Cannot send low credit email.")
        return False

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = settings.smtp_user
    msg['To'] = user_email
    msg['Subject'] = "Low Credit Alert - Audit My Websites"

    # Email body
    body = f"""
    Hello,

    We are reaching out to let you know that your Audit My Websites credit balance is low.
    
    Current Balance: {current_credits} credits.

    To ensure your audits continue running without interruption, please log in to your dashboard and top up your credits.

    If you have any questions, feel free to reply to this email.

    Best regards,
    The Audit My Websites Team
    """
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect to SMTP server and send email
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        
        logging.info(f"Low credit notification sent to {user_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send low credit email to {user_email}: {str(e)}")
        return False
