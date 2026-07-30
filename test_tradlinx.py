import asyncio
from playwright.async_api import async_playwright
import re

async def test_scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = 'https://www.tradlinx.com/ko/ocean-schedule-fcl?org=105169&des=105373&day=2026-07-30'
        await page.goto(url, timeout=30000)
        
        try:
            await page.wait_for_selector('a.vessel-name-fcl', timeout=15000)
            # Find rows
            # Based on Tradlinx UI, a row is usually a div containing the vessel name.
            # We can find all elements with class 'list-item-fcl' or similar, but since we know vessel-name-fcl:
            vessel_els = await page.query_selector_all('a.vessel-name-fcl')
            
            for v in vessel_els:
                row = await page.evaluate_handle('el => el.closest(".row") || el.closest("div[style*=\\"border-bottom\\"]") || el.parentElement.parentElement.parentElement', v)
                text = await row.inner_text()
                lines = [line.strip() for line in text.split('\\n') if line.strip()]
                print("LINES:", lines)
                print(text)
                
        except Exception as e:
            print('error:', e)
        await browser.close()

asyncio.run(test_scrape())
