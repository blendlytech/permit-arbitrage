"""
Citizenserve portal scraper.

Covers: Yavapai County AZ (installationID=300), City of Seminole (installationID=441).

Citizenserve portals use standard HTML forms and tables. The search is via
PERMITTING → SEARCH FOR PERMIT with fields for address, permit number, and
issue date.
"""
import asyncio
import logging
import re
from typing import Dict, List

from playwright.async_api import Page, TimeoutError as PwTimeout

from scrapers.config import DEFAULT_TIMEOUT, NICHE_KEYWORDS, SCHEMA_FIELDS, date_range
from scrapers.jurisdiction import Jurisdiction

logger = logging.getLogger("citizenserve")


async def _wait_ready(page: Page):
    """Wait for Citizenserve page to be ready."""
    await page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT)
    await asyncio.sleep(1)


async def scrape(
    page: Page,
    jurisdiction: Jurisdiction,
    days_back: int = 7,
    scrape_details: bool = True,
) -> List[Dict]:
    """
    Main Citizenserve scraper.

    Citizenserve doesn't have great date-range filtering via the UI,
    so we search broadly and post-filter by date + niche keywords.
    """
    start_date, end_date = date_range(days_back)
    all_permits: List[Dict] = []

    logger.info(f"Scraping {jurisdiction.name}")
    logger.info(f"  Portal: {jurisdiction.portal_url}")

    await page.goto(jurisdiction.portal_url, timeout=60_000)
    await _wait_ready(page)

    # Navigate to permit search — look for "PERMITTING" or "Search for Permit"
    search_link = page.locator(
        "a:has-text('PERMITTING'), a:has-text('Search'), "
        "a:has-text('Permit Search'), a:has-text('SEARCH FOR PERMIT')"
    ).first
    try:
        await search_link.click(timeout=10_000)
        await _wait_ready(page)
    except PwTimeout:
        logger.warning("Could not find search navigation link, trying current page")

    # Look for search form fields
    # Citizenserve typically has: permit number, address, date fields
    search_form = await page.evaluate("""() => {
        const inputs = document.querySelectorAll('input[type="text"], select');
        return Array.from(inputs).map(el => ({
            id: el.id,
            name: el.name,
            type: el.type,
            placeholder: el.placeholder || '',
            label: (() => {
                const label = el.closest('tr, div')?.querySelector('label, span');
                return label ? label.innerText.trim() : '';
            })()
        }));
    }""")
    logger.info(f"Found form fields: {search_form}")

    # Try to fill date fields if available
    date_fields = [f for f in search_form
                   if any(kw in (f["label"] + f["id"] + f["name"]).lower()
                          for kw in ["date", "issued", "from", "start"])]
    if date_fields:
        for field in date_fields:
            sel = f"#{field['id']}" if field["id"] else f"[name='{field['name']}']"
            try:
                await page.fill(sel, start_date)
                logger.info(f"Filled date field: {field['label'] or field['id']}")
            except Exception:
                pass

    # Submit the search
    submit = page.locator(
        "input[type='submit'], button[type='submit'], "
        "a:has-text('Search'), input[value='Search']"
    ).first
    try:
        await submit.click(timeout=10_000)
        await _wait_ready(page)
    except PwTimeout:
        logger.warning("Could not find/click submit button")

    # Parse results table
    results = await page.evaluate("""() => {
        const rows = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const trs = table.querySelectorAll('tr');
            if (trs.length < 2) continue;

            // Get headers
            const headers = Array.from(trs[0].querySelectorAll('th, td'))
                .map(th => th.innerText.trim().toLowerCase());
            if (headers.length < 3) continue;

            // Parse data rows
            for (let i = 1; i < trs.length; i++) {
                const cells = Array.from(trs[i].querySelectorAll('td'))
                    .map(td => td.innerText.trim());
                if (cells.length < 3) continue;

                const rowObj = {};
                headers.forEach((h, idx) => {
                    if (idx < cells.length) rowObj[h] = cells[idx];
                });

                // Get detail link if present
                const link = trs[i].querySelector('a');
                if (link) rowObj['_detail_url'] = link.href;

                rows.push(rowObj);
            }
        }
        return rows;
    }""")

    logger.info(f"Found {len(results)} raw result rows")

    # Map to schema and filter by niche keywords
    for row in results:
        permit = {f: "" for f in SCHEMA_FIELDS}

        for key, value in row.items():
            key_lower = key.lower()
            if any(kw in key_lower for kw in ["type", "description", "work"]):
                permit["permit_type"] = value
            elif any(kw in key_lower for kw in ["date", "issued"]):
                permit["issue_date"] = _normalize_date(value)
            elif any(kw in key_lower for kw in ["address", "location", "site"]):
                permit["property_address"] = value
            elif any(kw in key_lower for kw in ["owner", "applicant", "name"]):
                permit["owner_name"] = value
            elif any(kw in key_lower for kw in ["value", "valuation", "cost"]):
                permit["job_valuation"] = re.sub(r"[^0-9.]", "", value)

        # Niche filter
        combined_text = (permit["permit_type"] + " " + str(row)).lower()
        if any(kw in combined_text for kw in NICHE_KEYWORDS):
            if permit["property_address"]:
                all_permits.append(permit)

    logger.info(f"After niche filter: {len(all_permits)} permits")
    return all_permits


def _normalize_date(date_str: str) -> str:
    """Try to normalize date to YYYY-MM-DD."""
    try:
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3:
                return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except (IndexError, ValueError):
        pass
    return date_str
