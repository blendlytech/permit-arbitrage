import asyncio
import json
import os
import time
from datetime import datetime
import csv
import smtplib
import sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load .env variables natively
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# Import existing scraper logic
from scrapers.jurisdiction import find_jurisdiction
from scrapers.main import run_scraper
from scrapers.config import OUTPUT_DIR
from sync_leads import sync_lead, SUPABASE_URL, SUPABASE_KEY
import aiohttp

DB_FILE = os.path.join(OUTPUT_DIR, "seen_permits.db")

def init_db():
    """Initialize the SQLite database and migrate old JSON data if present."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS seen_permits (
                hash TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Migrate old JSON data if it exists
        old_json_db = os.path.join(OUTPUT_DIR, "seen_permits_db.json")
        if os.path.exists(old_json_db):
            try:
                with open(old_json_db, "r", encoding="utf-8") as f:
                    old_permits = json.load(f)
                
                conn.executemany(
                    "INSERT OR IGNORE INTO seen_permits (hash) VALUES (?)",
                    [(p,) for p in old_permits]
                )
                print(f"[DB] Migrated {len(old_permits)} records from old JSON DB.")
                os.rename(old_json_db, old_json_db + ".migrated")
            except Exception as e:
                print(f"[!] Failed to migrate old JSON db: {e}")

def is_permit_seen(p_hash):
    """Check if a permit hash exists in the database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM seen_permits WHERE hash = ?", (p_hash,))
        return cursor.fetchone() is not None

def mark_permits_seen(p_hashes):
    """Insert new permit hashes into the database."""
    if not p_hashes:
        return
    with sqlite3.connect(DB_FILE) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_permits (hash) VALUES (?)",
            [(h,) for h in p_hashes]
        )

def generate_permit_hash(permit):
    """Create a unique identifier for a permit based on its core fields."""
    # Combining Address, Type, and Date ensures high uniqueness
    addr = str(permit.get("property_address", "")).strip().lower()
    ptype = str(permit.get("permit_type", "")).strip().lower()
    date = str(permit.get("issue_date", "")).strip().lower()
    return f"{addr}|{ptype}|{date}"

def send_alert_email(new_permits, jurisdiction_name):
    """Send a premium HTML email alert with the fresh leads."""
    template_path = os.path.join(os.path.dirname(__file__), "outbound", "lead_alert_template.html")
    
    if not os.path.exists(template_path):
        print(f"[!] Template not found at {template_path}. Falling back to basic email.")
        return # Fallback logic could go here if needed
        
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # For now, we'll send a separate email for each lead to make it feel high-value
    # In the future, we can create a "Batch" template.
    for p in new_permits:
        try:
            val = float(str(p.get('job_valuation', 0)).replace(',', '').replace('$', ''))
        except:
            val = 0
            
        owner = f"{p.get('owner_first_name', '')} {p.get('owner_last_name', '')}".strip()
        if not owner: owner = p.get('owner_name', 'N/A')

        html_body = template.replace("{{ permit_type }}", str(p.get('permit_type', 'New Project')))
        html_body = html_body.replace("{{ property_address }}", str(p.get('property_address', 'N/A')))
        html_body = html_body.replace("{{ job_valuation }}", f"{val:,.2f}")
        html_body = html_body.replace("{{ issue_date }}", str(p.get('issue_date', 'N/A')))
        html_body = html_body.replace("{{ owner_name }}", owner)
        html_body = html_body.replace("{{ jurisdiction }}", jurisdiction_name)
        html_body = html_body.replace("{{ dashboard_url }}", "https://permit-leads.com/leads") # Update with real URL

        smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 465))
        sender_email = os.environ.get("SMTP_USER")
        sender_pass  = os.environ.get("SMTP_PASS")
        recipient_email = os.environ.get("SMTP_FROM_EMAIL")

        if not sender_pass:
            print("[!] Email not sent: 'SMTP_PASS' is not set.")
            return

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"🚨 NEW PROJECT: {p.get('permit_type')} in {jurisdiction_name}"
        msg['From'] = f"PermitLeads <{sender_email}>"
        msg['To'] = recipient_email
        
        msg.attach(MIMEText(html_body, 'html'))
        
        try:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(sender_email, sender_pass)
                server.send_message(msg)
            print(f"[✓] Premium alert sent for {p.get('property_address')}")
        except Exception as e:
            print(f"[!] Email failed: {e}")

async def run_monitor_cycle(context, jurisdiction_query="Leon", days_back=1):
    """Run a single iteration of the monitoring cycle."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting monitor cycle for '{jurisdiction_query}'...")
    
    j = find_jurisdiction(jurisdiction_query)
    if not j:
        print(f"Jurisdiction '{jurisdiction_query}' not found.")
        return

    # Run the scraper (with homeowner-only filtering enabled)
    # We only need to look back 1 day since this runs every 30 mins
    permits = await run_scraper(
        j, 
        days_back=days_back, 
        scrape_details=True, 
        homeowner_only=True,
        context=context
    )
    
    new_leads = []
    new_hashes = []
    
    for p in permits:
        p_hash = generate_permit_hash(p)
        if not is_permit_seen(p_hash):
            new_hashes.append(p_hash)
            new_leads.append(p)
            
    if new_leads:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Detected {len(new_leads)} NET-NEW permits!")
        
        # Save updated history
        mark_permits_seen(new_hashes)
        
        # Export a mini-CSV of just the fresh leads
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fresh_csv = os.path.join(OUTPUT_DIR, f"FRESH_LEADS_{j.name.replace(' ', '_')}_{timestamp}.csv")
        
        if new_leads:
            keys = new_leads[0].keys()
            with open(fresh_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(new_leads)
            print(f"Saved fresh leads to: {fresh_csv}")
            
        # Trigger email/notification alert
        send_alert_email(new_leads, j.name)
        
        # Sync to Supabase Cloud
        if SUPABASE_URL and SUPABASE_KEY:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Syncing {len(new_leads)} leads to Supabase...")
            try:
                async with aiohttp.ClientSession() as session:
                    sync_count = 0
                    for lead in new_leads:
                        # Ensure hash is in the lead dict for sync
                        lead['hash'] = generate_permit_hash(lead)
                        lead['jurisdiction'] = j.name
                        if await sync_lead(session, lead):
                            sync_count += 1
                    print(f"[✓] Successfully synced {sync_count} leads to cloud database.")
            except Exception as e:
                print(f"[!] Supabase sync failed: {e}")
        
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No new permits found in this cycle.")

async def run_daemon():
    print("=" * 60)
    print("Permit Arbitrage Daemon - Real-time Lead Monitor")
    print("=" * 60)
    
    # Configuration
    TARGET_JURISDICTIONS = ["Leon", "Polk", "Pasco", "Hillsborough", "Tampa"]
    POLL_INTERVAL_MINUTES = 30
    
    init_db()
    
    from playwright.async_api import async_playwright
    from scrapers.config import HEADLESS, SLOW_MO
    
    while True:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=HEADLESS,
                    slow_mo=SLOW_MO,
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                
                for jurisdiction in TARGET_JURISDICTIONS:
                    try:
                        await run_monitor_cycle(context, jurisdiction_query=jurisdiction, days_back=1)
                    except Exception as e:
                        print(f"Error during monitor cycle for {jurisdiction}: {e}")
                    
                    # Brief pause between jurisdictions to be polite to servers
                    await asyncio.sleep(5)
                    
                await browser.close()
        except Exception as e:
            print(f"Playwright runtime error: {e}")
            
        print(f"\nCompleted cycle for all {len(TARGET_JURISDICTIONS)} jurisdictions.")
        print(f"Waiting {POLL_INTERVAL_MINUTES} minutes until next check...")
        await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    asyncio.run(run_daemon())
