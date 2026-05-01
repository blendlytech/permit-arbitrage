"""
Permit Arbitrage Scraper — Main CLI Entry Point

Usage:
    python -m scrapers.main                          # Interactive menu
    python -m scrapers.main --jurisdiction "Leon"     # By name fragment
    python -m scrapers.main --id 1                    # By CSV row number
    python -m scrapers.main --id 1 --days 14          # Custom timeframe
    python -m scrapers.main --id 1 --no-details       # Skip detail pages (faster)
    python -m scrapers.main --list                    # List all jurisdictions
"""
import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright, BrowserContext

# Add project root to sys.path to resolve package imports when run as a script
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scrapers.config import (
    LOG_DIR,
    OUTPUT_DIR,
    PLATFORM_ACCELA,
    PLATFORM_CITIZENSERVE,
    PLATFORM_CLICK2GOV,
    PLATFORM_SMARTGOV,
    HEADLESS,
    SLOW_MO,
    SCHEMA_FIELDS,
)
from scrapers.jurisdiction import (
    Jurisdiction,
    find_by_id,
    find_jurisdiction,
    load_jurisdictions,
)
from scrapers.platforms import accela, citizenserve, click2gov, smartgov

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

log_file = os.path.join(
    LOG_DIR, f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ── Platform → scraper dispatch ───────────────────────────────────────────────
SCRAPERS = {
    PLATFORM_ACCELA: accela.scrape,
    PLATFORM_CITIZENSERVE: citizenserve.scrape,
    PLATFORM_CLICK2GOV: click2gov.scrape,
    PLATFORM_SMARTGOV: smartgov.scrape,
}


def list_all_jurisdictions():
    """Print all jurisdictions from the CSV."""
    jurisdictions = load_jurisdictions()
    print("\n" + "=" * 80)
    print(f"  {'ID':<4} {'Jurisdiction':<45} {'Platform':<15}")
    print("=" * 80)
    for j in jurisdictions:
        print(f"  {j.id:<4} {j.name:<45} {j.platform:<15}")
    print("=" * 80)
    print(f"  Total: {len(jurisdictions)} jurisdictions\n")


def interactive_select() -> Jurisdiction:
    """Interactive jurisdiction selection menu."""
    jurisdictions = load_jurisdictions()
    list_all_jurisdictions()
    while True:
        choice = input("Enter jurisdiction ID (or name fragment): ").strip()
        if choice.isdigit():
            j = find_by_id(int(choice), jurisdictions)
        else:
            j = find_jurisdiction(choice, jurisdictions)
        if j:
            print(f"\n  Selected: {j.name}")
            print(f"  Platform: {j.platform}")
            print(f"  URL:      {j.portal_url}\n")
            confirm = input("Proceed? (y/n): ").strip().lower()
            if confirm in ("y", "yes", ""):
                return j
        else:
            print("  Not found. Try again.")


def export_csv(permits: list, jurisdiction: Jurisdiction):
    """Export permits to a CSV file."""
    if not permits:
        logger.warning("No permits to export")
        return None

    # Clean filename
    name_clean = jurisdiction.name.replace(",", "").replace(" ", "_")
    filename = f"{name_clean}_Leads_{datetime.now().strftime('%Y%m%d')}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        for permit in permits:
            # Only write schema fields (exclude internal fields)
            row = {k: permit.get(k, "") for k in SCHEMA_FIELDS}
            writer.writerow(row)

    logger.info(f"Exported {len(permits)} permits to: {filepath}")
    return filepath


def export_json(permits: list, jurisdiction: Jurisdiction):
    """Export permits to a JSON file (schema-compliant)."""
    if not permits:
        return None

    name_clean = jurisdiction.name.replace(",", "").replace(" ", "_")
    filename = f"{name_clean}_Leads_{datetime.now().strftime('%Y%m%d')}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    # Only write schema fields
    clean_permits = [
        {k: p.get(k, "") for k in SCHEMA_FIELDS}
        for p in permits
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean_permits, f, indent=2)

    logger.info(f"Exported JSON to: {filepath}")
    return filepath


async def run_scraper(jurisdiction: Jurisdiction, days_back: int = 7,
                      scrape_details: bool = True, homeowner_only: bool = False,
                      context: BrowserContext = None):
    """Launch browser, run the appropriate scraper, export results."""

    scraper_fn = SCRAPERS.get(jurisdiction.platform)
    if not scraper_fn:
        logger.error(f"No scraper for platform: {jurisdiction.platform}")
        return []

    logger.info("=" * 60)
    logger.info(f"STARTING SCRAPE: {jurisdiction.name}")
    logger.info(f"  Platform:  {jurisdiction.platform}")
    logger.info(f"  Portal:    {jurisdiction.portal_url}")
    logger.info(f"  Days back: {days_back}")
    logger.info(f"  Details:   {'yes' if scrape_details else 'no'}")
    logger.info("=" * 60)

    async def _execute_scrape(ctx):
        page = await ctx.new_page()
        try:
            for attempt in range(1, 4):
                try:
                    return await scraper_fn(
                        page=page,
                        jurisdiction=jurisdiction,
                        days_back=days_back,
                        scrape_details=scrape_details,
                    )
                except Exception as e:
                    if attempt < 3:
                        logger.warning(f"Scraper error on attempt {attempt}: {e}. Retrying in {attempt * 5}s...")
                        await asyncio.sleep(attempt * 5)
                    else:
                        logger.error(f"Scraper error on attempt {attempt}: {e}", exc_info=True)
                        return []
        finally:
            await page.close()

    if context:
        permits = await _execute_scrape(context)
    else:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=HEADLESS,
                slow_mo=SLOW_MO,
            )
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            try:
                permits = await _execute_scrape(ctx)
            finally:
                await browser.close()

    # Filter homeowner-only permits
    if homeowner_only and permits:
        filtered = []
        for p in permits:
            c_name = str(p.get("contractor_name", "")).strip().lower()
            if not c_name or "owner" in c_name:
                filtered.append(p)
            else:
                logger.info(f"  [Filter] Dropped {p.get('permit_type')} at {p.get('property_address')} (Has Contractor: {p.get('contractor_name')})")
        
        logger.info(f"Filtered down from {len(permits)} to {len(filtered)} homeowner-only permits.")
        permits = filtered

    # Parse Owner Name into First and Last Name
    for p in permits:
        owner = str(p.get("owner_name", "")).strip()
        if owner and not p.get("owner_first_name"):
            # Simple heuristic: if it contains a comma (e.g. "DOE JOHN"), reverse it
            if "," in owner:
                parts = owner.split(",")
                last = parts[0].strip()
                first = parts[1].strip().split()[0] if parts[1].strip() else ""
                p["owner_first_name"] = first.title()
                p["owner_last_name"] = last.title()
            else:
                # E.g. "JOHN DOE"
                parts = owner.split()
                if len(parts) >= 2:
                    p["owner_first_name"] = parts[0].title()
                    p["owner_last_name"] = " ".join(parts[1:]).title()
                else:
                    p["owner_first_name"] = owner.title()
                    p["owner_last_name"] = ""

    # Export results
    if permits:
        csv_path = export_csv(permits, jurisdiction)
        json_path = export_json(permits, jurisdiction)
        print("\n" + "=" * 60)
        print(f"  [OK] {len(permits)} permits scraped!")
        print(f"  CSV: {csv_path}")
        print(f"  JSON: {json_path}")
        print("=" * 60 + "\n")
    else:
        print("\n  [!] No permits found. Check logs for details.\n")

    return permits


def main():
    parser = argparse.ArgumentParser(
        description="Permit Arbitrage Scraper — Extract permit leads from government portals"
    )
    parser.add_argument("--list", action="store_true",
                        help="List all jurisdictions from the CSV")
    parser.add_argument("--id", type=int, default=None,
                        help="Jurisdiction ID from the CSV")
    parser.add_argument("--jurisdiction", "-j", type=str, default=None,
                        help="Jurisdiction name fragment (e.g. 'Leon')")
    parser.add_argument("--days", type=int, default=7,
                        help="Number of days to look back (default: 7)")
    parser.add_argument("--no-details", action="store_true",
                        help="Skip detail page scraping (faster, but no owner/valuation)")
    parser.add_argument("--homeowner-only", action="store_true",
                        help="Only save permits without a contractor tied to them")
    args = parser.parse_args()

    if args.list:
        list_all_jurisdictions()
        return

    # Resolve jurisdiction
    if args.id:
        j = find_by_id(args.id)
        if not j:
            print(f"  ❌ Jurisdiction ID {args.id} not found.")
            sys.exit(1)
    elif args.jurisdiction:
        j = find_jurisdiction(args.jurisdiction)
        if not j:
            print(f"  ❌ No jurisdiction matching '{args.jurisdiction}'.")
            sys.exit(1)
    else:
        j = interactive_select()

    # Run the scraper
    asyncio.run(run_scraper(j, days_back=args.days,
                            scrape_details=not args.no_details,
                            homeowner_only=args.homeowner_only))


if __name__ == "__main__":
    main()
