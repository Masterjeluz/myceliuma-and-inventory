"""Take BIG #38 automation screenshots with Playwright (Edge headless)."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

SHOTS_DIR = Path("docs/r38-shots")
SHOTS_DIR.mkdir(exist_ok=True)

async def take_screenshots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        
        base = "http://127.0.0.1:8888"
        
        # 1. Automation overview page
        print("Taking automation-overview.png...")
        await page.goto(f"{base}/automation", wait_until="networkidle")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=str(SHOTS_DIR / "automation-overview.png"), full_page=True)
        print("[OK] automation-overview.png")
        
        # 2. Automation detail - waiting (run that's waiting for human)
        print("Taking automation-detail-waiting.png...")
        await page.goto(f"{base}/automation", wait_until="networkidle")
        run_links = await page.query_selector_all("a[href^='/automation/auto_']")
        hrefs = []
        for link in run_links:
            href = await link.get_attribute("href")
            if href:
                hrefs.append(href)
        
        found_waiting = False
        for href in hrefs:
            await page.goto(f"{base}{href}", wait_until="networkidle")
            await page.wait_for_timeout(500)
            content = await page.content()
            if "waiting_for_human" in content or "Waiting" in content:
                await page.screenshot(path=str(SHOTS_DIR / "automation-detail-waiting.png"), full_page=True)
                print("[OK] automation-detail-waiting.png")
                found_waiting = True
                break
        if not found_waiting:
            print("No waiting run found, skipping")
        
        # 3. Automation detail - completed
        print("Taking automation-detail-completed.png...")
        await page.goto(f"{base}/automation", wait_until="networkidle")
        run_links = await page.query_selector_all("a[href^='/automation/auto_']")
        hrefs = []
        for link in run_links:
            href = await link.get_attribute("href")
            if href:
                hrefs.append(href)
        
        found_completed = False
        for href in hrefs:
            await page.goto(f"{base}{href}", wait_until="networkidle")
            await page.wait_for_timeout(500)
            content = await page.content()
            if "completed" in content and "waiting_for_human" not in content:
                await page.screenshot(path=str(SHOTS_DIR / "automation-detail-completed.png"), full_page=True)
                print("[OK] automation-detail-completed.png")
                found_completed = True
                break
        if not found_completed:
            print("No completed run found, skipping")
        
        # 4. Guide page with automation
        print("Taking guide-automation.png...")
        await page.goto(f"{base}/guide", wait_until="networkidle")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOTS_DIR / "guide-automation.png"), full_page=True)
        print("[OK] guide-automation.png")
        
        # 5. Mobile dashboard
        print("Taking mobile-automation.png...")
        await page.goto(f"{base}/mobile", wait_until="networkidle")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOTS_DIR / "mobile-automation.png"), full_page=True)
        print("[OK] mobile-automation.png")
        
        # 6. Morning report
        print("Taking morning-automation.png...")
        await page.goto(f"{base}/reports/morning", wait_until="networkidle")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOTS_DIR / "morning-automation.png"), full_page=True)
        print("[OK] morning-automation.png")
        
        await browser.close()

asyncio.run(take_screenshots())
print("All screenshots saved to docs/r38-shots/")