"""
Click2Gov portal scraper.

Covers: Seminole County FL, Lake Worth Beach FL.

Click2Gov portals typically lack explicit Record Type dropdowns, so we search
broadly by address/date and post-filter descriptions for niche keywords.
"""
import asyncio
import logging
import re
from typing import Dict, List

from playwright.async_api import Page, TimeoutError as PwTimeout

from scrapers.config import DEFAULT_TIMEOUT, NICHE_KEYWORDS, SCHEMA_FIELDS, date_range
from scrapers.jurisdiction import Jurisdiction

logger = logging.getLogger("click2gov")


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
    Main Click2Gov scraper.

    Click2Gov portals often have minimal search fields (permit number, address).
    Strategy: search with wildcards, parse all results, post-filter by keywords.
    """
    start_date, end_date = date_range(days_back)
    all_permits: List[Dict] = []

    logger.info(f"Scraping {jurisdiction.name}")
    logger.info(f"  Portal: {jurisdiction.portal_url}")

    await page.goto(jurisdiction.portal_url, timeout=60_000)
    await _wait_ready(page)

    # Click2Gov usually presents a search form immediately
    # Look for available fields
    form_fields = await page.evaluate("""() => {
        const inputs = document.querySelectorAll(
            'input[type="text"], input[type="date"], select'
        );
        return Array.from(inputs).map(el => ({
            id: el.id,
            name: el.name,
            type: el.type,
            placeholder: el.placeholder || '',
            label: (() => {
                const lbl = document.querySelector(`label[for="${el.id}"]`);
                if (lbl) return lbl.innerText.trim();
                const parent = el.closest('div, td, li');
                const span = parent?.querySelector('label, span');
                return span ? span.innerText.trim() : '';
            })()
        }));
    }""")
    logger.info(f"Click2Gov form fields: {form_fields}")

    # Try to fill date fields
    for field in form_fields:
        field_text = (field["label"] + field["id"] + field["name"] + field["placeholder"]).lower()

        if any(kw in field_text for kw in ["issue", "application", "date", "from", "start"]):
            sel = f"#{field['id']}" if field["id"] else f"[name='{field['name']}']"
            try:
                await page.fill(sel, start_date)
                logger.info(f"Filled date: {field['label'] or field['id']} = {start_date}")
            except Exception:
                pass

    # Try wildcard address search (some Click2Gov portals need at least one field)
    for field in form_fields:
        field_text = (field["label"] + field["id"] + field["name"]).lower()
        if any(kw in field_text for kw in ["address", "street", "site"]):
            sel = f"#{field['id']}" if field["id"] else f"[name='{field['name']}']"
            try:
                await page.fill(sel, "*")  # wildcard
                logger.info(f"Filled address wildcard: {field['label'] or field['id']}")
                break
            except Exception:
                pass

    # Submit
    submit = page.locator(
        "input[type='submit'], button[type='submit'], "
        "button:has-text('Search'), a:has-text('Search'), "
        "input[value='Search'], input[value='Go']"
    ).first
    try:
        await submit.click(timeout=10_000)
        await _wait_ready(page)
        await asyncio.sleep(2)
    except PwTimeout:
        logger.warning("Submit button not found")
        return all_permits

    # Parse results — Click2Gov typically renders a table or card list
    results = await page.evaluate("""() => {
        const rows = [];

        // Try table format
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

        // If no table, try div/card-based layout
        if (rows.length === 0) {
            const cards = document.querySelectorAll(
                'div.permit-card, div.result-item, div[class*="permit"], li[class*="result"]'
            );
            for (const card of cards) {
                rows.push({
                    _raw_text: card.innerText.trim(),
                    _detail_url: (card.querySelector('a') || {}).href || ''
                });
            }
        }

        return rows;
    }""")

    logger.info(f"Found {len(results)} raw results")

    # Map to schema
    for row in results:
        permit = {f: "" for f in SCHEMA_FIELDS}

        if "_raw_text" in row:
            # Card-based layout — parse the text block
            text = row["_raw_text"]
            permit = _parse_text_block(text)
        else:
            for key, value in row.items():
                if key.startswith("_"):
                    continue
                key_lower = key.lower()
                if any(kw in key_lower for kw in ["type", "description", "work", "category"]):
                    permit["permit_type"] = value
                elif any(kw in key_lower for kw in ["date", "issued"]):
                    permit["issue_date"] = _normalize_date(value)
                elif any(kw in key_lower for kw in ["address", "location", "site"]):
                    permit["property_address"] = value
                elif any(kw in key_lower for kw in ["owner", "applicant"]):
                    permit["owner_name"] = value
                elif any(kw in key_lower for kw in ["value", "valuation", "cost"]):
                    permit["job_valuation"] = re.sub(r"[^0-9.]", "", value)

        # Post-filter by niche keywords
        full_text = (permit.get("permit_type", "") + " " + str(row)).lower()
        if any(kw in full_text for kw in NICHE_KEYWORDS):
            if permit.get("property_address"):
                all_permits.append(permit)

    logger.info(f"After niche filter: {len(all_permits)} permits")
    return all_permits


def _parse_text_block(text: str) -> Dict:
    """Parse a free-text permit card into structured fields."""
    permit = {f: "" for f in SCHEMA_FIELDS}
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    date_pat = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
    addr_pat = re.compile(r"\d+.*?\b(ST|AVE|DR|RD|LN|CT|BLVD|WAY|PL|CIR|TRL|ROAD|STREET|DRIVE|COURT|LANE|BOULEVARD|TRAIL)\b", re.I)

    for line in lines:
        if date_pat.search(line) and not permit["issue_date"]:
            match = date_pat.search(line)
            permit["issue_date"] = _normalize_date(match.group())
        elif addr_pat.search(line) and not permit["property_address"]:
            permit["property_address"] = line
        elif any(kw in line.lower() for kw in NICHE_KEYWORDS):
            if not permit["permit_type"]:
                permit["permit_type"] = line

    return permit


def _normalize_date(date_str: str) -> str:
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except (IndexError, ValueError):
        pass
    return date_str
