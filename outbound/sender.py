"""
Outbound Sales Engine — Phase 4

Reads Prospects_List CSV, deduplicates and validates emails,
renders the correct template, and sends cold outreach via Domain SMTP.

⚠️  HUMAN-IN-THE-LOOP: No real emails are sent until the operator
    explicitly approves the preview batch.
"""

import csv
import json
import os
import re
import smtplib
import sys
import time
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from outbound.templates import (
    render_subject_a,
    render_subject_b,
    render_body_a,
    render_body_b,
)

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("outbound")

# ── .env loader ────────────────────────────────────────────────────
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
SEND_LOG = os.path.join(OUTPUT_DIR, "email_send_log.json")

# ── Email Validation / Quality Filters ─────────────────────────────
_JUNK_PATTERNS = [
    r"@sentry\.",           # Wix/Sentry tracking hashes
    r"@wixpress\.",
    r"\.gov$",              # Government emails — never cold-email these
    r"@talgov\.com",        # Tallahassee city gov (disguised as .com)
    r"noreply@",
    r"no-reply@",
    r"donotreply@",
    r"info@example\.com",
]

def _is_valid_prospect_email(email: str) -> bool:
    """Return False for junk, tracking, or government emails."""
    if not email or not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return False
    for pat in _JUNK_PATTERNS:
        if re.search(pat, email, re.IGNORECASE):
            return False
    return True


def _deduplicate_prospects(prospects: list) -> list:
    """Remove duplicate rows by email address, keeping the first occurrence."""
    seen_emails = set()
    deduped = []
    for p in prospects:
        email = p.get("Owner Email", "").strip().lower()
        if email and email not in seen_emails:
            seen_emails.add(email)
            deduped.append(p)
    return deduped


# ── Load Prospects ─────────────────────────────────────────────────
def load_prospects(csv_path: str) -> list:
    """Load, validate, and deduplicate the prospect list."""
    if not os.path.exists(csv_path):
        logger.error(f"Prospect file not found: {csv_path}")
        return []

    raw = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw.append(row)

    logger.info(f"Loaded {len(raw)} raw rows from {os.path.basename(csv_path)}")

    # Filter invalid emails
    valid = [r for r in raw if _is_valid_prospect_email(r.get("Owner Email", ""))]
    rejected = len(raw) - len(valid)
    if rejected:
        logger.warning(f"Filtered out {rejected} invalid/junk emails")

    # Deduplicate
    deduped = _deduplicate_prospects(valid)
    dupes = len(valid) - len(deduped)
    if dupes:
        logger.warning(f"Removed {dupes} duplicate emails")

    logger.info(f"Final prospect count: {len(deduped)}")
    return deduped


# ── Permit Count Helper ────────────────────────────────────────────
def get_permit_count(county_keyword: str) -> int:
    """Scan the output folder and sum permit counts from the most recent leads CSVs."""
    total = 0
    for fname in os.listdir(OUTPUT_DIR):
        if fname.endswith(".csv") and "_Leads_" in fname and county_keyword.replace(" ", "_") in fname:
            fpath = os.path.join(OUTPUT_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                total += sum(1 for _ in reader)
    return total if total > 0 else 132  # fallback to a reasonable default


# ── Send Log ───────────────────────────────────────────────────────
def _load_send_log() -> list:
    if os.path.exists(SEND_LOG):
        with open(SEND_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_send_log(log: list):
    with open(SEND_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def _already_emailed(email: str) -> bool:
    """Check if we've already sent to this email in the current campaign."""
    log = _load_send_log()
    return any(entry.get("email", "").lower() == email.lower() for entry in log)


# ── RPV Data Systems Sender ──────────────────────────────────────────
def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a single cold email via RPV domain SMTP (Spaceship)."""
    smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    sender_email = os.environ.get("SMTP_USER")
    sender_pass  = os.environ.get("SMTP_PASS")
    from_name    = os.environ.get("SMTP_FROM_NAME", "Clay Mills | PermitLeads")

    if not sender_pass:
        logger.error("SMTP_PASS not set in .env — cannot send.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{sender_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"SMTP error sending to {to_email} via {smtp_host}: {e}")
        return False


# ── Main Campaign Runner ──────────────────────────────────────────
def run_campaign(
    csv_path: str,
    county: str,
    niche: str = "Pool & Reroof",
    template: str = "B",
    sender_name: str = "James",
    dry_run: bool = True,
    delay_seconds: int = 45,
):
    """
    Execute the outbound email campaign.

    Args:
        csv_path:       Path to the Prospects_List CSV.
        county:         Target county name (e.g. "Leon County").
        niche:          Target niche label.
        template:       "A" (standard) or "B" (small-city).
        sender_name:    Name to sign off with.
        dry_run:        If True, preview only — no emails sent.
        delay_seconds:  Pause between sends (avoids Gmail rate limits).
    """
    prospects = load_prospects(csv_path)
    if not prospects:
        logger.error("No valid prospects to email. Aborting.")
        return

    permit_count = get_permit_count(county.split()[0])

    # ── Build the email batch ──────────────────────────────────────
    batch = []
    for p in prospects:
        email = p["Owner Email"].strip()
        first_name = p.get("Owner First Name", "").strip()

        # If we don't have a first name, use a friendly generic
        if not first_name:
            first_name = "there"

        if template.upper() == "A":
            subject = render_subject_a(permit_count, niche, county)
            body = render_body_a(first_name, permit_count, niche, county, sender_name)
        else:
            subject = render_subject_b(permit_count, county)
            body = render_body_b(first_name, permit_count, county, sender_name)

        batch.append({
            "business": p.get("Business Name", ""),
            "email": email,
            "first_name": first_name,
            "niche": p.get("Niche", ""),
            "subject": subject,
            "body": body,
        })

    # ── Preview ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  OUTBOUND CAMPAIGN PREVIEW -- {county}")
    print(f"  Template: {'Standard (A)' if template.upper() == 'A' else 'Small-City (B)'}")
    print(f"  Permit Count: {permit_count}")
    print(f"  Prospects: {len(batch)}")
    print("=" * 70)

    for i, item in enumerate(batch, 1):
        already = " [SKIP -- already sent]" if _already_emailed(item["email"]) else ""
        print(f"\n  [{i}] {item['business']}{already}")
        print(f"      To:      {item['email']}")
        print(f"      Subject: {item['subject']}")
        print(f"      Body:    {item['body'][:120]}...")

    print("\n" + "=" * 70)

    if dry_run:
        print("\n  [!] DRY RUN -- No emails were sent.")
        print("  To send for real, re-run with:  --send")
        print("=" * 70)
        return

    # -- Human-in-the-loop gate --
    print("\n  [!] HUMAN APPROVAL REQUIRED")
    confirm = input(f"  Send {len(batch)} emails? Type 'YES' to confirm: ").strip()
    if confirm != "YES":
        print("  Aborted by operator.")
        return

    # ── Send loop ──────────────────────────────────────────────────
    send_log = _load_send_log()
    sent = 0
    skipped = 0

    for item in batch:
        if _already_emailed(item["email"]):
            logger.info(f"Skipping (already sent): {item['email']}")
            skipped += 1
            continue

        logger.info(f"Sending to {item['email']}...")
        success = send_email(item["email"], item["subject"], item["body"])

        send_log.append({
            "email": item["email"],
            "business": item["business"],
            "niche": item["niche"],
            "subject": item["subject"],
            "status": "sent" if success else "failed",
            "timestamp": datetime.now().isoformat(),
        })
        _save_send_log(send_log)

        if success:
            sent += 1
            logger.info(f"  [OK] Sent ({sent}/{len(batch) - skipped})")
        else:
            logger.error(f"  [FAIL] Failed for {item['email']}")

        # Throttle to avoid SMTP rate limits
        if sent < len(batch) - skipped:
            logger.info(f"  Waiting {delay_seconds}s before next send...")
            time.sleep(delay_seconds)

    print("\n" + "=" * 70)
    print(f"  CAMPAIGN COMPLETE")
    print(f"  Sent: {sent}  |  Skipped: {skipped}  |  Total: {len(batch)}")
    print(f"  Log saved to: {SEND_LOG}")
    print("=" * 70)


# ── CLI Entry Point ────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 4 — Outbound Sales Engine")
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to Prospects_List CSV (auto-detects if omitted)")
    parser.add_argument("--county", type=str, default="Leon County",
                        help="Target county name")
    parser.add_argument("--niche", type=str, default="Pool & Reroof",
                        help="Target niche label")
    parser.add_argument("--template", type=str, default="B", choices=["A", "B"],
                        help="Email template: A (standard) or B (small-city)")
    parser.add_argument("--sender", type=str, default="James",
                        help="Your sign-off name")
    parser.add_argument("--send", action="store_true",
                        help="Actually send emails (default is dry-run preview)")
    parser.add_argument("--delay", type=int, default=45,
                        help="Seconds between sends (default: 45)")
    args = parser.parse_args()

    # Auto-detect CSV if not specified
    csv_path = args.csv
    if not csv_path:
        county_slug = args.county.replace(" ", "_")
        candidate = os.path.join(OUTPUT_DIR, f"Prospects_List_{county_slug}.csv")
        if os.path.exists(candidate):
            csv_path = candidate
        elif os.path.exists(os.path.join(OUTPUT_DIR, "Prospects_List.csv")):
            csv_path = os.path.join(OUTPUT_DIR, "Prospects_List.csv")
        else:
            logger.error("No Prospects_List CSV found. Run Phase 3 (enrichment) first.")
            sys.exit(1)

    run_campaign(
        csv_path=csv_path,
        county=args.county,
        niche=args.niche,
        template=args.template,
        sender_name=args.sender,
        dry_run=not args.send,
        delay_seconds=args.delay,
    )
