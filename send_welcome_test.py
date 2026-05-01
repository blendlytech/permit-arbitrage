import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env
def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

load_env()

def send_welcome_test():
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outbound", "welcome_pilot.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_body = f.read()

    smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    sender_email = os.environ.get("SMTP_USER")
    sender_pass  = os.environ.get("SMTP_PASS")
    recipient_email = "cmills79@gmail.com"

    if not sender_pass:
        print("[!] Email not sent: 'SMTP_PASS' is not set.")
        return

    msg = MIMEMultipart("alternative")
    msg['Subject'] = "🎁 Your First 3 Polk County Leads (PermitLeads Pilot)"
    msg['From'] = f"PermitLeads <{sender_email}>"
    msg['To'] = recipient_email
    
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print(f"[✓] Welcome Pilot email sent to {recipient_email}")
    except Exception as e:
        print(f"[!] Email failed: {e}")

if __name__ == "__main__":
    send_welcome_test()
