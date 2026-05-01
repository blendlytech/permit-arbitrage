"""
Data Enrichment Pipeline (Phase 3)

Integrates with Google Places API to find contractors and 
Apollo/Hunter to find executive emails.
"""
import os
import csv
import asyncio
import logging
import aiohttp

# ensure .env is loaded first
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from scrapers.config import OUTPUT_DIR

logger = logging.getLogger("enrichment")

def get_api_key(name):
    key = os.environ.get(name)
    if not key:
        logger.error(f"Missing API key: {name} in .env")
    return key

async def get_contractors_from_directory(county: str, niche: str, limit: int = 50):
    """Scrape YellowPages for contractors (100% Free workaround for Google Maps API)."""
    from playwright.async_api import async_playwright
    import urllib.parse
    
    # E.g., "Pool Contractors" and "Leon County, FL"
    location = county if "," in county else f"{county}, FL"
    
    query = urllib.parse.quote_plus(f"{niche} Contractors")
    geo = urllib.parse.quote_plus(location)
    url = f"https://www.yellowpages.com/search?search_terms={query}&geo_location_terms={geo}"
    
    results = []
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()
        
        logger.info(f"Navigating to YellowPages: {url}")
        await page.goto(url, timeout=60000)
        
        try:
            await page.wait_for_selector("div.result", timeout=10000)
        except Exception:
            logger.warning("No results found on YellowPages or page blocked.")
            await browser.close()
            return results
            
        cards = await page.locator("div.result").all()
        for card in cards:
            if len(results) >= limit:
                break
                
            try:
                name_el = card.locator("a.business-name")
                name = await name_el.inner_text() if await name_el.count() > 0 else ""
                
                phone_el = card.locator("div.phones")
                phone = await phone_el.inner_text() if await phone_el.count() > 0 else ""
                
                web_el = card.locator("a.track-visit-website")
                website = await web_el.get_attribute("href") if await web_el.count() > 0 else ""
                
                if name and website:
                    results.append({
                        "business_name": name.strip(),
                        "website": website,
                        "phone": phone.strip(),
                        "niche": niche,
                        "county": county
                    })
            except Exception as e:
                logger.debug(f"Error parsing YP card: {e}")
                
        await browser.close()
        
    return results

import re

async def scrape_emails_from_website(url: str):
    """Fallback: Scrape emails directly from the contractor's homepage."""
    if not url.startswith("http"):
        url = "http://" + url
        
    emails = set()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    found = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
                    for e in found:
                        # ignore common image extensions mistakenly matched
                        if not any(e.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']):
                            emails.add(e.lower())
    except Exception as e:
        pass
        
    return [{"email": e, "first_name": "", "last_name": "", "position": "Website Scrape"} for e in emails][:1]

async def find_emails(domain: str):
    """Find emails for a given domain using Hunter.io, Apollo.io, or fallback scraper."""
    if not domain or domain == "None":
        return []
        
    clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

    hunter_key = os.environ.get("HUNTER_API_KEY")
    apollo_key = os.environ.get("APOLLO_API_KEY")
    
    emails = []
    
    if hunter_key:
        emails = await _find_emails_hunter(clean_domain, hunter_key)
    elif apollo_key:
        emails = await _find_emails_apollo(clean_domain, apollo_key)
        
    # If API failed (e.g. Apollo free tier block) or no keys provided, fallback to raw scraping
    if not emails:
        logger.info(f"API fallback: Scraping {domain} for emails directly...")
        emails = await scrape_emails_from_website(domain)
        
    return emails

async def _find_emails_hunter(domain: str, api_key: str):
    url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                emails = []
                for email_data in data.get("data", {}).get("emails", []):
                    position = (email_data.get("position") or "").lower()
                    person = {
                        "email": email_data.get("value"),
                        "first_name": email_data.get("first_name", ""),
                        "last_name": email_data.get("last_name", ""),
                        "position": email_data.get("position", "")
                    }
                    if any(role in position for role in ["owner", "founder", "ceo", "president"]):
                        emails.insert(0, person)
                    else:
                        emails.append(person)
                return emails
            return []

async def _find_emails_apollo(domain: str, api_key: str):
    url = "https://api.apollo.io/v1/mixed_people/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Api-Key": api_key
    }
    payload = {
        "q_organization_domains": domain,
        "person_titles": ["owner", "founder", "ceo", "president", "partner"],
        "page": 1
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                emails = []
                for person in data.get("people", []):
                    if person.get("email"):
                        emails.append({
                            "email": person.get("email"),
                            "first_name": person.get("first_name", ""),
                            "last_name": person.get("last_name", ""),
                            "position": person.get("title", "")
                        })
                return emails
            else:
                logger.error(f"Apollo API Error: {response.status} {await response.text()}")
            return []

async def build_prospect_list(county: str):
    """Phase 3 Workflow: Generate the prospects list for a given county."""
    logger.info(f"Building prospect list for {county}...")
    niches = ["Pool", "Roofing"]
    all_prospects = []
    
    for niche in niches:
        logger.info(f"Searching for {niche} contractors...")
        contractors = await get_contractors_from_directory(county, niche, limit=50)
        logger.info(f"Found {len(contractors)} contractors.")
        
        for c in contractors:
            website = c.get("website")
            if website:
                logger.info(f"Finding emails for {website}...")
                emails = await find_emails(website)
                
                if emails:
                    best_email = emails[0]
                    all_prospects.append({
                        "Business Name": c.get("business_name"),
                        "Owner First Name": best_email.get("first_name", ""),
                        "Owner Last Name": best_email.get("last_name", ""),
                        "Owner Email": best_email.get("email"),
                        "Position": best_email.get("position", ""),
                        "Phone": c.get("phone"),
                        "Website": website,
                        "Niche": c.get("niche"),
                        "County": c.get("county")
                    })
                    
    # Generate CSV
    if all_prospects:
        csv_path = os.path.join(OUTPUT_DIR, f"Prospects_List_{county.replace(' ', '_')}.csv")
        keys = all_prospects[0].keys()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_prospects)
        logger.info(f"Successfully wrote {len(all_prospects)} prospects to {csv_path}")
    else:
        logger.warning(f"No prospects found with valid emails for {county}.")
        
    return all_prospects

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", type=str, required=True, help="Target county to build prospect list for")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s", stream=sys.stdout)
    
    asyncio.run(build_prospect_list(args.county))
