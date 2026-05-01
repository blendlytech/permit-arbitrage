"""
SmartGov Community portal scraper.

Covers: Coconino County, AZ.

SmartGov uses a public search portal with fields for Address, Parcel,
and Issued/Applied Date. Results display in HTML grids.
"""
import asyncio
import logging
import re
from typing import Dict, List

from playwright.async_api import Page, TimeoutError as PwTimeout

from scrapers.config import DEFAULT_TIMEOUT, NICHE_KEYWORDS, SCHEMA_FIELDS, date_range
from scrapers.jurisdiction import Jurisdiction

logger = logging.getLogger("smartgov")


async def _wait_ready(page: Page):
    await page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT)
    await asyncio.sleep(1)


async def scrape(
    page: Page,
    jurisdiction: Jurisdiction,
    days_back: int = 7,
    scrape_details: bool = True,
) -> List[Dict]:
    """
    Main SmartGov scraper.

    SmartGov portals have a search interface with Address, Parcel,
    and date fields. Results are in HTML grid tables.
    """
    start_date, end_date = date_range(days_back)
    all_permits: List[Dict] = []

    logger.info(f"Scraping {jurisdiction.name}")
    logger.info(f"  Portal: {jurisdiction.portal_url}")

    await page.goto(jurisdiction.portal_url, timeout=60_000)
    await _wait_ready(page)

    # Look for search / permit link
    search_link = page.locator(
        "a:has-text('Search'), a:has-text('Permits'), "
        "a:has-text('Building'), a:has-text('Records')"
    ).first
    try:
        await search_link.click(timeout=10_000)
        await _wait_ready(page)
    except PwTimeout:
        logger.info("No search link found, trying current page")

    # Discover form fields
    form_fields = await page.evaluate("""() => {
        const inputs = document.querySelectorAll(
            'input[type="text"], input[type="date"], input[type="search"], select'
        );
        return Array.from(inputs).map(el => ({
            id: el.id,
            name: el.name,
            type: el.type,
            placeholder: el.placeholder || '',
            label: (() => {
                const lbl = document.querySelector(`label[for="${el.id}"]`);
                if (lbl) return lbl.innerText.trim();
                const parent = el.closest('div, td, tr');
                const span = parent?.querySelector('label, span');
                return span ? span.innerText.trim() : '';
            })()
        }));
    }""")
    logger.info(f"SmartGov form fields: {form_fields}")

    # Fill date fields
    for field in form_fields:
        text = (field["label"] + field["id"] + field["name"] + field["placeholder"]).lower()
        sel = f"#{field['id']}" if field["id"] else f"[name='{field['name']}']"

        if any(kw in text for kw in ["issued", "start", "from", "begin"]):
            try:
                await page.fill(sel, start_date)
                logger.info(f"Filled start date: {start_date}")
            except Exception:
                pass
        elif any(kw in text for kw in ["end", "to", "through"]):
            try:
                await page.fill(sel, end_date)
                logger.info(f"Filled end date: {end_date}")
            except Exception:
                pass

    # Submit
    submit = page.locator(
        "button[type='submit'], input[type='submit'], "
        "button:has-text('Search'), a:has-text('Search')"
    ).first
    try:
        await submit.click(timeout=10_000)
        await _wait_ready(page)
        await asyncio.sleep(2)
    except PwTimeout:
        logger.warning("Submit not found")

    # Parse results grid
    results = await page.evaluate("""() => {
        const rows = [];
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const trs = table.querySelectorAll('tr');
            if (trs.length < 2) continue;

            const headers = Array.from(trs[0].querySelectorAll('th, td'))
                .map(th => th.innerText.trim().toLowerCase());
            if (headers.length < 2) continue;

            for (let i = 1; i < trs.length; i++) {
                const cells = Array.from(trs[i].querySelectorAll('td'))
                    .map(td => td.innerText.trim());
                if (cells.length < 2) continue;

                const rowObj = {};
                headers.forEach((h, idx) => {
                    if (idx < cells.length) rowObj[h] = cells[idx];
                });
                const link = trs[i].querySelector('a');
                if (link) rowObj['_detail_url'] = link.href;
                rows.push(rowObj);
            }
        }
        return rows;
    }""")

    logger.info(f"Found {len(results)} raw results")

    # Map to schema and niche-filter
    for row in results:
        permit = {f: "" for f in SCHEMA_FIELDS}
        for key, value in row.items():
            if key.startswith("_"):
                continue
            kl = key.lower()
            if any(kw in kl for kw in ["type", "description", "work", "category", "permit"]):
                permit["permit_type"] = value
            elif any(kw in kl for kw in ["date", "issued", "applied"]):
                permit["issue_date"] = _normalize_date(value)
            elif any(kw in kl for kw in ["address", "location", "site", "property"]):
                permit["property_address"] = value
            elif any(kw in kl for kw in ["owner", "applicant", "name"]):
                permit["owner_name"] = value
            elif any(kw in kl for kw in ["value", "valuation", "cost", "amount"]):
                permit["job_valuation"] = re.sub(r"[^0-9.]", "", value)

        full_text = (permit.get("permit_type", "") + " " + str(row)).lower()
        if any(kw in full_text for kw in NICHE_KEYWORDS):
            if permit.get("property_address"):
                all_permits.append(permit)

    logger.info(f"After niche filter: {len(all_permits)} permits")
    return all_permits


def _normalize_date(date_str: str) -> str:
    try:
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3:
                return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except (IndexError, ValueError):
        pass
    return date_str
