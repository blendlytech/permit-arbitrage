import asyncio
from playwright.async_api import async_playwright
import os

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Leon County URL
        url = "https://aca-prod.accela.com/leonco/Cap/CapHome.aspx?module=Building"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=60000)
        await asyncio.sleep(5)
        
        # Perform search
        # Fill date range (past 30 days)
        print("Filling date range...")
        await page.locator("input[id*='txtGSStartDate']").fill("03/29/2026")
        await page.locator("input[id*='txtGSEndDate']").fill("04/28/2026")
        
        # Click search
        print("Clicking search...")
        await page.locator("a[id*='btnNewSearch']").click()
        await asyncio.sleep(10) # wait for results to load
        
        # Save HTML
        html_content = await page.content()
        output_file = os.path.join("C:\\Users\\DELL\\Permit_Arbitrage", "scratch_page.html")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"HTML saved to {output_file}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
