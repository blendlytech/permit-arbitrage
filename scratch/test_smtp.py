import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env
env_file = ".env"
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

smtp_host = os.environ.get("SMTP_HOST")
smtp_port = int(os.environ.get("SMTP_PORT", 465))
sender_email = os.environ.get("SMTP_USER")
sender_pass = os.environ.get("SMTP_PASS")

print(f"Testing SMTP: {smtp_host}:{smtp_port}")
print(f"User: {sender_email}")

msg = MIMEMultipart()
msg["Subject"] = "SMTP Test"
msg["From"] = sender_email
msg["To"] = sender_email  # Send to self
msg.attach(MIMEText("This is a test of the SMTP configuration.", "plain"))

try:
    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender_email, sender_pass)
        server.send_message(msg)
    print("SUCCESS: SMTP test email sent.")
except Exception as e:
    print(f"FAILURE: {e}")
