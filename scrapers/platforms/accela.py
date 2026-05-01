"""
Accela Citizen Access (ACA) scraper.

Covers ~14 of 20 jurisdictions. Accela ACA is an ASP.NET WebForms app with
a consistent structure across deployments:

  Search Form → Results Grid → Detail Pages

Key selectors discovered via live scouting of Leon County's portal:
  - Record Type:  select#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType
  - Start Date:   input#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate
  - End Date:     input#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate
  - Search Btn:   a#ctl00_PlaceHolderMain_btnNewSearch
  - Pagination:   a.aca_simple_text containing "Next >"
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional

from playwright.async_api import Page, TimeoutError as PwTimeout

from scrapers.config import (
    DEFAULT_TIMEOUT,
    NICHE_KEYWORDS,
    SCHEMA_FIELDS,
    date_range,
)
from scrapers.jurisdiction import Jurisdiction

logger = logging.getLogger("accela")

# ── Selectors (with fallbacks) ────────────────────────────────────────────────
# Primary IDs are from the Leon County scout; fallback patterns cover
# jurisdiction-specific variations.

SEL_RECORD_TYPE = [
    "select#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType",
    "select[id*='ddlGSPermitType']",
    "select[id*='PermitType']",
    "select[id*='RecordType']",
]
SEL_START_DATE = [
    "input#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate",
    "input[id*='txtGSStartDate']",
    "input[id*='StartDate']",
]
SEL_END_DATE = [
    "input#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate",
    "input[id*='txtGSEndDate']",
    "input[id*='EndDate']",
]
SEL_SEARCH_BTN = [
    "a#ctl00_PlaceHolderMain_btnNewSearch",
    "a[id*='btnNewSearch']",
    "input[id*='btnNewSearch']",
    "a:has-text('Search')",
]
SEL_RESULTS_TABLE = [
    "table[id*='dvSearchList'] table.ACA_Grid_Alternate",
    "div[id*='dvSearchList'] table",
    "table.ACA_Grid_Alternate",
    "div.ACA_TabRow table",
]
SEL_NEXT_PAGE = "a.aca_simple_text:has-text('Next')"
SEL_LOADING = "div.ACA_Loading, div[id*='divGlobalLoading']"


async def _find(page: Page, selectors: list, timeout: int = 10_000):
    """Try multiple selectors, return the first match."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=timeout)
            return el
        except (PwTimeout, Exception):
            continue
    return None


async def _wait_loading_done(page: Page, timeout: int = DEFAULT_TIMEOUT):
    """Wait for Accela's loading overlay to disappear."""
    try:
        loading = page.locator(SEL_LOADING).first
        await loading.wait_for(state="hidden", timeout=timeout)
    except (PwTimeout, Exception):
        pass  # overlay may not appear for fast queries
    await page.wait_for_load_state("networkidle", timeout=timeout)


async def _select_record_type(page: Page, record_type: str) -> bool:
    """
    Select a record type from the dropdown. Returns True if found.
    """
    dropdown = await _find(page, SEL_RECORD_TYPE)
    if not dropdown:
        logger.warning("Record Type dropdown not found")
        return False

    # Get all options
    options = await dropdown.evaluate(
        """el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))"""
    )

    # Find the best match
    target = record_type.lower().strip()
    for opt in options:
        if target in opt["text"].lower():
            await dropdown.select_option(value=opt["value"])
            logger.info(f"Selected Record Type: {opt['text']}")
            await asyncio.sleep(1)  # wait for postback
            return True

    logger.warning(f"Record type '{record_type}' not found in dropdown. "
                   f"Available: {[o['text'] for o in options]}")
    return False


async def _fill_dates(page: Page, start_date: str, end_date: str):
    """Fill the date range fields."""
    start_el = await _find(page, SEL_START_DATE)
    end_el = await _find(page, SEL_END_DATE)

    if start_el:
        await start_el.click(click_count=3)  # select all
        await start_el.fill(start_date)
        logger.info(f"Start Date: {start_date}")
    else:
        logger.warning("Start Date field not found")

    if end_el:
        await end_el.click(click_count=3)
        await end_el.fill(end_date)
        logger.info(f"End Date: {end_date}")
    else:
        logger.warning("End Date field not found")


async def _click_search(page: Page) -> bool:
    """Click the search button and wait for results."""
    btn = await _find(page, SEL_SEARCH_BTN)
    if not btn:
        logger.error("Search button not found")
        return False
    await btn.click()
    logger.info("Search submitted, waiting for results…")
    await _wait_loading_done(page)
    await asyncio.sleep(2)
    return True


async def _parse_results_page(page: Page) -> List[Dict]:
    """
    Parse the results grid on the current page.
    Returns a list of dicts with basic fields from the grid.
    """
    rows = []

    # Try to find the results table
    table = await _find(page, SEL_RESULTS_TABLE, timeout=5_000)
    if not table:
        # Fallback: look for any table rows with permit data
        logger.info("Primary results table not found, trying fallback…")

    # Extract all result rows using JS for reliability
    data = await page.evaluate("""() => {
        const rows = [];
        // Find all table rows that look like permit results
        const allRows = document.querySelectorAll('tr');
        for (const tr of allRows) {
            const cells = tr.querySelectorAll('td');
            if (cells.length < 3) continue;

            // Extract text from each cell
            const cellTexts = Array.from(cells).map(c => c.innerText.trim());

            // Look for a link (permit number) in the row
            const link = tr.querySelector('a[href*="Cap/CapDetail"]');
            const detailUrl = link ? link.href : '';

            rows.push({
                cells: cellTexts,
                detail_url: detailUrl,
                permit_number: link ? link.innerText.trim() : ''
            });
        }
        return rows;
    }""")

    for row_data in data:
        cells = row_data["cells"]
        # Accela grid columns typically: checkbox | date | record# | type | address | status | description | subtype
        # The exact order varies, so we'll try to identify by content patterns
        record = _parse_grid_row(cells, row_data.get("detail_url", ""))
        if record:
            rows.append(record)

    logger.info(f"Parsed {len(rows)} rows from current page")
    return rows


def _parse_grid_row(cells: list, detail_url: str) -> Optional[Dict]:
    """
    Parse a single grid row into a permit record.
    Uses heuristics since column order varies by jurisdiction.
    """
    record = {f: "" for f in SCHEMA_FIELDS}
    record["_detail_url"] = detail_url

    date_pattern = re.compile(r"\d{2}/\d{2}/\d{4}")

    for cell in cells:
        if not cell:
            continue
        # Date detection
        if date_pattern.match(cell) and not record["issue_date"]:
            record["issue_date"] = _normalize_date(cell)
        # Address detection (starts with numbers, contains street patterns)
        elif (re.search(r"^\d+.*?\b(ST|AVE|DR|RD|LN|CT|BLVD|WAY|PL|CIR|TRL|ROAD|STREET|DRIVE|COURT|LANE|BOULEVARD|TRAIL)\b", cell, re.I)
              and not record["property_address"]):
            record["property_address"] = cell
        # Permit type detection (contains niche keywords)
        elif any(kw in cell.lower() for kw in NICHE_KEYWORDS + ["residential", "commercial", "permit"]):
            if not record["permit_type"]:
                record["permit_type"] = cell

    # Add length validation to prevent whole-page garbage rows
    if len(record["permit_type"]) > 100 or len(record["property_address"]) > 200:
        return None

    return record if (record["property_address"] and record["permit_type"] and record["issue_date"]) else None


def _normalize_date(date_str: str) -> str:
    """Convert MM/DD/YYYY to YYYY-MM-DD."""
    try:
        parts = date_str.split("/")
        return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except (IndexError, ValueError):
        return date_str


async def _scrape_detail_page(page: Page, detail_url: str) -> Dict:
    """
    Navigate to a permit detail page and extract owner name + job valuation.
    """
    extras = {"owner_name": "", "job_valuation": "", "contractor_name": "", "owner_email": ""}

    try:
        await page.goto(detail_url, timeout=DEFAULT_TIMEOUT)
        await _wait_loading_done(page)

        # Extract owner info, contractor info, and emails
        page_data = await page.evaluate("""() => {
            let owner = '';
            let contractor = '';
            let email = '';
            
            // Email extraction (regex for common email patterns in text)
            const emailMatch = document.body.innerText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
            if (emailMatch) email = emailMatch[0];

            // Owner section
            const ownerSection = document.querySelector(
                'div[id*="divOwnerList"], div[id*="Owner"], ' +
                'table[id*="Owner"]'
            );
            if (ownerSection) owner = ownerSection.innerText.trim();
            else {
                const labels = document.querySelectorAll('span, td, div');
                for (const el of labels) {
                    if (el.innerText && el.innerText.includes('Owner:')) {
                        owner = el.parentElement.innerText.trim();
                        break;
                    }
                }
            }

            // Contractor / Licensed Professional section
            const lpSection = document.querySelector(
                'table[summary*="Licensed Professional"], div[id$="LicenseeList_updatePanel"], div[id*="divLicensedProfessional"]'
            );
            if (lpSection) {
                contractor = lpSection.innerText.trim();
            } else {
                const labels = document.querySelectorAll('span, td, th');
                for (const el of labels) {
                    const txt = el.innerText ? el.innerText.trim() : '';
                    if (txt === 'Licensed Professional:' || txt === 'Contractor:' || txt === 'Licensed Professional') {
                        let next = el.nextElementSibling;
                        if (!next && el.parentElement) {
                            next = el.parentElement.nextElementSibling;
                        }
                        if (next) {
                            contractor = next.innerText.trim();
                        } else {
                            contractor = el.parentElement.innerText.trim();
                        }
                        break;
                    }
                }
            }

            return { owner, contractor, email };
        }""")

        if page_data.get("email"):
            extras["owner_email"] = page_data["email"]

        if page_data.get("owner"):
            # Split and filter out noise (Accessibility links, headers, etc)
            noise = [
                "skip to main content", "accessibility", "leon county permits", 
                "owner:", "owner", "owner information", "select", "search"
            ]
            lines = [l.strip() for l in page_data["owner"].split("\n") if l.strip()]
            for line in lines:
                if not any(n in line.lower() for n in noise):
                    extras["owner_name"] = line
                    break

        if page_data.get("contractor"):
            lines = [l.strip() for l in page_data["contractor"].split("\n") if l.strip() and "Leon County Permits" not in l]
            for line in lines:
                if line.lower() not in ("licensed professional:", "licensed professional", "contractor:", "contractor"):
                    extras["contractor_name"] = line
                    break

        # Try to get valuation from "More Details" → "Application Information"
        more_details = page.locator("a#lnkMoreDetail, a:has-text('More Details')")
        try:
            await more_details.click(timeout=5_000)
            await asyncio.sleep(1)

            # Expand "Application Information"
            app_info = page.locator("a#lnkASI, a:has-text('Application Information')")
            await app_info.click(timeout=5_000)
            await asyncio.sleep(1)

            # Look for valuation field
            val_text = await page.evaluate("""() => {
                const spans = document.querySelectorAll('span, td');
                for (const el of spans) {
                    const txt = el.innerText || '';
                    if (txt.toLowerCase().includes('valuation') ||
                        txt.toLowerCase().includes('job value') ||
                        txt.toLowerCase().includes('estimated cost')) {
                        // Get the next sibling or adjacent cell
                        const next = el.nextElementSibling ||
                                     el.parentElement.nextElementSibling;
                        if (next) return next.innerText.trim();
                    }
                }
                return '';
            }""")

            if val_text:
                # Clean to number
                val_clean = re.sub(r"[^0-9.]", "", val_text)
                extras["job_valuation"] = val_clean
        except (PwTimeout, Exception):
            logger.debug("Could not expand More Details for valuation")

    except Exception as e:
        logger.warning(f"Error scraping detail page: {e}")

    return extras


async def scrape(
    page: Page,
    jurisdiction: Jurisdiction,
    days_back: int = 7,
    scrape_details: bool = True,
) -> List[Dict]:
    """
    Main Accela scraper entry point.

    Args:
        page: Playwright page object
        jurisdiction: Jurisdiction dataclass from CSV
        days_back: How many days back to search
        scrape_details: Whether to click into each record for owner/valuation

    Returns:
        List of permit dicts conforming to the schema
    """
    start_date, end_date = date_range(days_back)
    all_permits: List[Dict] = []

    # Parse niche record types from the CSV
    # e.g. "Residential Pool, Residential Reroof, Commercial Pool"
    raw_types = jurisdiction.niche_record_types
    # Strip any trailing citation text
    raw_types = re.split(r"(?:aca-prod|civicplus|citizenserve|access\.okc)", raw_types)[0]
    record_types = [t.strip().rstrip(".") for t in raw_types.split(",") if t.strip()]

    if not record_types:
        record_types = ["Residential Reroof", "Residential Pool"]
        logger.warning(f"No record types parsed from CSV, using defaults: {record_types}")

    logger.info(f"Scraping {jurisdiction.name}")
    logger.info(f"  Portal: {jurisdiction.portal_url}")
    logger.info(f"  Record types: {record_types}")
    logger.info(f"  Date range: {start_date} – {end_date}")

    # Navigate to the portal
    await page.goto(jurisdiction.portal_url, timeout=60_000)
    await _wait_loading_done(page)

    # Check for CAPTCHA
    captcha = await page.locator("iframe[src*='captcha'], div[class*='captcha'], #recaptcha").count()
    if captcha > 0:
        logger.error("⚠️  CAPTCHA DETECTED — waiting for human operator…")
        print("\n" + "=" * 60)
        print("  CAPTCHA DETECTED — Please solve it in the browser window.")
        print("  Press Enter here when done…")
        print("=" * 60)
        input()

    base_url = page.url  # save for navigating back after detail pages

    try:
        for record_type in record_types:
            logger.info(f"\n--- Searching for: {record_type} ---")

            # Navigate back to search page if needed
            if page.url != base_url:
                await page.goto(base_url, timeout=60_000)
                await _wait_loading_done(page)

            # Fill search form
            type_found = await _select_record_type(page, record_type)
            if not type_found:
                logger.warning(f"Skipping record type '{record_type}' (not in dropdown)")
                continue

            await _fill_dates(page, start_date, end_date)
            search_ok = await _click_search(page)
            if not search_ok:
                continue

            # Check for "no results" message
            no_results = await page.locator("span:has-text('No matching records'), "
                                            "span:has-text('0 result')").count()
            if no_results > 0:
                logger.info(f"No results for {record_type}")
                continue

            # Parse results across all pages
            page_num = 1
            while True:
                logger.info(f"  Parsing results page {page_num}…")
                rows = await _parse_results_page(page)
                all_permits.extend(rows)

                # Check for next page
                next_btn = page.locator(SEL_NEXT_PAGE)
                try:
                    await next_btn.wait_for(state="visible", timeout=3_000)
                    await next_btn.click()
                    await _wait_loading_done(page)
                    page_num += 1
                except PwTimeout:
                    break  # no more pages
    except Exception as e:
        logger.error(f"Error during scrape loop: {e}. Returning partial results.")

    logger.info(f"\nTotal grid results: {len(all_permits)}")

    # Optionally scrape detail pages for owner + valuation
    if scrape_details and all_permits:
        logger.info("Scraping detail pages for owner names & valuations concurrently…")
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent detail tabs
        context = page.context
        
        async def fetch_detail(i, permit, detail_url):
            async with semaphore:
                logger.info(f"  Detail {i + 1}/{len(all_permits)}: {detail_url[:80]}…")
                # Create a temporary page for this request
                detail_page = await context.new_page()
                try:
                    extras = await _scrape_detail_page(detail_page, detail_url)
                    permit.update(extras)
                finally:
                    await detail_page.close()
                await asyncio.sleep(1) # Be polite per request

        tasks = []
        for i, permit in enumerate(all_permits):
            detail_url = permit.pop("_detail_url", "")
            if detail_url:
                tasks.append(fetch_detail(i, permit, detail_url))
                
        if tasks:
            await asyncio.gather(*tasks)
    else:
        # Remove internal field
        for p in all_permits:
            p.pop("_detail_url", None)

    logger.info(f"Scraping complete: {len(all_permits)} permits found for {jurisdiction.name}")
    return all_permits
