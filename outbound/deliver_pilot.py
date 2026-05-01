"""
Pilot Program Delivery Script — Phase 4
Delivers the professional Pilot HTML email to a newly converted subscriber.
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

def deliver_pilot(recipient_email, recipient_name):
    template_path = os.path.join(os.path.dirname(__file__), "welcome_pilot.html")
    
    if not os.path.exists(template_path):
        print(f"Error: Template not found at {template_path}")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Personalization
    html_content = html_content.replace("Your First 3 Leads", f"Hi {recipient_name}, Your First 3 Leads")

    smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    sender_email = os.environ.get("SMTP_USER")
    sender_pass = os.environ.get("SMTP_PASS")
    from_name = os.environ.get("SMTP_FROM_NAME", "Clay Mills | PermitLeads")

    if not sender_pass:
        print("Error: SMTP_PASS not set.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Polk County Pilot Access: Verified Leads & 60-Day Lockout"
    msg["From"] = f"{from_name} <{sender_email}>"
    msg["To"] = recipient_email
    
    # Plain text version for better deliverability
    text_version = f"Hi {recipient_name},\n\nWelcome to the PermitLeads Exclusive Pilot. You can view your first leads and territory lockout here: https://www.rareplantvendors.com/permits"
    
    msg.attach(MIMEText(text_version, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print(f"SUCCESS: Pilot package delivered to {recipient_email}")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python deliver_pilot.py <email> <name>")
        sys.exit(1)
    
    deliver_pilot(sys.argv[1], sys.argv[2])
