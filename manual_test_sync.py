import asyncio
import aiohttp
import os
from daemon import run_monitor_cycle, init_db
from playwright.async_api import async_playwright

async def test():
    print("=" * 60)
    print("PermitLeads - Cloud Sync Verification Test")
    print("=" * 60)
    
    init_db()
    
    async with async_playwright() as pw:
        print("[*] Launching browser...")
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # We'll test Tampa to ensure we find fresh data for the end-to-end test
        print("[*] Running scrape and sync for City of Tampa (Last 7 days)...")
        try:
            await run_monitor_cycle(context, jurisdiction_query="Tampa", days_back=7)
            print("\n[✓] Test cycle completed.")
        except Exception as e:
            print(f"\n[!] Test failed: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
