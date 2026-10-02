from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings
import logging

router = APIRouter(prefix="/api")

class ContactSchema(BaseModel):
    name: str
    email: str
    company_name: str = None
    website_url: str
    message: str

@router.post("/contact")
async def send_contact_email(contact: ContactSchema):
    """
    Handle contact form submission and send email via SMTP
    """
    if not settings.smtp_user or not settings.smtp_password:
        logging.error("SMTP credentials not configured in settings")
        raise HTTPException(status_code=500, detail="Server email configuration missing")

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = settings.smtp_user
    recipients = [r.strip() for r in settings.contact_recipients.split(",")]
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = "auditmywebsites"

    # Email body
    body = f"""
    New inquiry received from the Audit My Websites contact form:

    Full Name: {contact.name}
    Email: {contact.email}
    Company: {contact.company_name or 'N/A'}
    Website: {contact.website_url}

    Message:
    {contact.message}
    """
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect to SMTP server and send email
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        
        return {"status": "success", "message": "Email sent successfully"}
    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
