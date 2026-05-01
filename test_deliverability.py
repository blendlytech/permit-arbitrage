import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

def test_send(recipient_email):
    smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    sender_email = os.environ.get("SMTP_USER")
    sender_pass = os.environ.get("SMTP_PASS")
    from_name = os.environ.get("SMTP_FROM_NAME", "Clay Mills | PermitLeads")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Deliverability Test - PermitLeads"
    msg["From"] = f"{from_name} <{sender_email}>"
    msg["To"] = recipient_email
    
    text = "This is a plain text test email to verify deliverability."
    html = "<html><body><h1>Deliverability Test</h1><p>This is a test email.</p></body></html>"
    
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print(f"SUCCESS: Test email sent to {recipient_email}")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    test_send("scmillsc0809@gmail.com")
