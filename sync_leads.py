import os
import json
import asyncio
import aiohttp
import csv
import glob
from datetime import datetime

# Load .env natively
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

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

async def sync_lead(session, lead):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
        
    url = f"{SUPABASE_URL}/rest/v1/permit_leads"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    # Map CSV fields to Supabase fields
    # Try to extract a clean valuation
    val_raw = lead.get("job_valuation", "0")
    try:
        val = float(str(val_raw).replace("$", "").replace(",", "").strip())
    except:
        val = 0

    # Ensure hash exists (daemon uses a pipe-separated string)
    p_hash = lead.get("hash")
    if not p_hash:
        addr = str(lead.get("property_address", "")).strip().lower()
        ptype = str(lead.get("permit_type", "")).strip().lower()
        date = str(lead.get("issue_date", "")).strip().lower()
        p_hash = f"{addr}|{ptype}|{date}"
    
    payload = {
        "hash": p_hash,
        "owner_name": lead.get("owner_name"),
        "owner_first_name": lead.get("owner_first_name"),
        "owner_last_name": lead.get("owner_last_name"),
        "property_address": lead.get("property_address"),
        "permit_type": lead.get("permit_type"),
        "job_valuation": val,
        "issue_date": lead.get("issue_date"),
        "jurisdiction": lead.get("jurisdiction") or "Florida",
        "raw_data": lead
    }
    
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status in [200, 201]:
            return True
        elif resp.status == 409: # Conflict/Duplicate
            return True
        else:
            # print(f"Error syncing lead: {await resp.text()}")
            return False

async def main():
    print("=" * 60)
    print("PermitLeads - Supabase Cloud Sync")
    print("=" * 60)

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[!] Missing Supabase credentials in .env. Please add SUPABASE_URL and SUPABASE_SERVICE_KEY.")
        return

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    csv_files = glob.glob(os.path.join(output_dir, "FRESH_LEADS_*.csv"))
    
    if not csv_files:
        print("[i] No fresh lead CSVs found in output directory.")
        return

    async with aiohttp.ClientSession() as session:
        total_synced = 0
        for csv_file in csv_files:
            print(f"[*] Processing {os.path.basename(csv_file)}...")
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    count = 0
                    for row in reader:
                        if await sync_lead(session, row):
                            count += 1
                    print(f" [OK] Synced {count} leads.")
                    total_synced += count
            except Exception as e:
                print(f" [!] Error processing file: {e}")
        
        print("-" * 60)
        print(f"Sync Complete. Total Leads Pushed: {total_synced}")

if __name__ == "__main__":
    asyncio.run(main())
