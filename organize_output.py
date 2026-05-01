import os
import shutil
import json
import csv
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LEADS_DIR = os.path.join(OUTPUT_DIR, "leads_archive")
PROSPECTS_DIR = os.path.join(OUTPUT_DIR, "prospects_archive")
TEMP_DIR = os.path.join(OUTPUT_DIR, "system_cache")

def ensure_dirs():
    for d in [LEADS_DIR, PROSPECTS_DIR, TEMP_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)

def organize():
    ensure_dirs()
    print("--- Organizing output folder ---")
    
    inventory = {
        "total_leads": 0,
        "counties": {},
        "last_cleanup": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    files = os.listdir(OUTPUT_DIR)
    for f in files:
        fpath = os.path.join(OUTPUT_DIR, f)
        
        # Skip directories
        if os.path.isdir(fpath):
            continue
            
        # ── 1. Archive Leads (CSV and JSON) ─────────────────────────────────
        if "_Leads_" in f or "FRESH_LEADS_" in f:
            # Extract county name for inventory
            county = "Unknown"
            if "FRESH_LEADS_" in f:
                parts = f.replace("FRESH_LEADS_", "").split("_")
                county = parts[0].replace(",", "")
            elif "_Leads_" in f:
                county = f.split("_Leads_")[0]
            
            # Count leads in CSV
            if f.endswith(".csv"):
                try:
                    with open(fpath, 'r', encoding='utf-8') as csvfile:
                        count = sum(1 for _ in csvfile) - 1
                        inventory["total_leads"] += count
                        inventory["counties"][county] = inventory["counties"].get(county, 0) + count
                except:
                    pass
            
            shutil.move(fpath, os.path.join(LEADS_DIR, f))
            print(f"  [ARCHIVED] {f} -> leads_archive/")

        # ── 2. Archive Prospects ────────────────────────────────────────────
        elif "Prospects_List" in f:
            shutil.move(fpath, os.path.join(PROSPECTS_DIR, f))
            print(f"  [ARCHIVED] {f} -> prospects_archive/")

        # ── 3. Clean System Cache ──────────────────────────────────────────
        elif f.endswith(".json") and f != "email_send_log.json" and f != "seen_permits_db.json" and f != "inventory.json":
            shutil.move(fpath, os.path.join(TEMP_DIR, f))
            print(f"  [CACHED] {f} -> system_cache/")

        # ── 4. Delete Junk ──────────────────────────────────────────────────
        elif f == "Draft_Email.txt":
            os.remove(fpath)
            print(f"  [DELETED] {f}")

    # ── 5. Save Inventory Summary ──────────────────────────────────────────
    with open(os.path.join(OUTPUT_DIR, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)
    
    print("\nCleanup Complete!")
    print(f"   Processed {inventory['total_leads']} leads across {len(inventory['counties'])} counties.")
    print(f"   Inventory summary saved to output/inventory.json")

if __name__ == "__main__":
    organize()
