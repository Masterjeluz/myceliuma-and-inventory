"""Take BIG #39 hardware-reality screenshots with Playwright.

Seeds tmp DBs via b39_shots.py, serves them on 127.0.0.1:8899
in a background thread, captures 6 PNGs into docs/r39-shots/.
No taskkill, no real DBs touched.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TMP = r"C:\Users\Jelles\AppData\Local\Temp\b39_shots"
PORT = 8899

os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(TMP, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    TMP, "shots-chat.db")

import uvicorn  # noqa: E402
import coordinator.app.main as main_mod  # noqa: E402


def run_server():
    uvicorn.run(main_mod.app, host="127.0.0.1", port=PORT,
                log_level="warning")


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(3)

result = subprocess.run(
    [sys.executable, "scripts/b39_shots.py"],
    capture_output=True, text=True, cwd=".",
    env={**os.environ, "B39_SHOT_TMP": TMP})
print(result.stdout[-2000:])
if result.returncode != 0:
    print("Seed script failed:", result.stderr[-2000:])
    sys.exit(1)

print("Seed done, taking screenshots...")

SHOTS_DIR = Path("docs/r39-shots")
SHOTS_DIR.mkdir(exist_ok=True)

import asyncio  # noqa: E402


async def take_screenshots():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge",
                                            headless=True)
        page = await browser.new_page(
            viewport={"width": 1440, "height": 900})
        base = f"http://127.0.0.1:{PORT}"

        await page.goto(f"{base}/nodes", wait_until="networkidle")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=str(SHOTS_DIR / "nodes-1440.png"),
            full_page=True)
        print("ok nodes-1440.png")

        await page.goto(
            f"{base}/nodes?check_cap=camera.snapshot",
            wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(
            path=str(SHOTS_DIR / "routing-1440.png"),
            full_page=True)
        print("ok routing-1440.png")

        await page.goto(
            f"{base}/world?show=missions,nodes,hardware,compute",
            wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(
            path=str(SHOTS_DIR / "world-1440.png"),
            full_page=True)
        print("ok world-1440.png")

        await page.goto(f"{base}/mobile", wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(
            path=str(SHOTS_DIR / "mobile-1440.png"),
            full_page=True)
        print("ok mobile-1440.png")

        try:
            panel = await page.query_selector("#nodes")
            if panel is not None:
                await panel.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                await panel.screenshot(
                    path=str(SHOTS_DIR / "hardware-1440.png"))
                print("ok hardware-1440.png")
            else:
                print("nodes panel missing, skipping hardware shot")
        except Exception as error:
            print(f"hardware shot failed: {error}")

        await page.goto(f"{base}/guide", wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(
            path=str(SHOTS_DIR / "guide-1440.png"),
            full_page=True)
        print("ok guide-1440.png")

        await browser.close()


asyncio.run(take_screenshots())
print("All screenshots saved to docs/r39-shots/")
