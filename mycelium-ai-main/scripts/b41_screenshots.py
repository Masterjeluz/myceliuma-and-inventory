"""Take BIG #41 V2 screenshots with Playwright (Edge headless).

Seeds tmp DBs via b41_shots.py, serves them on 127.0.0.1:8899
in a background thread, captures 7 PNGs into docs/r41-shots/.
No real DBs touched.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TMP = r"C:\Users\Jelles\AppData\Local\Temp\b41_shots"
PORT = 8899

os.makedirs(TMP, exist_ok=True)
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
    [sys.executable, "scripts/b41_shots.py"],
    capture_output=True, text=True, cwd=".",
    env={**os.environ, "B41_SHOT_TMP": TMP})
print(result.stdout[-2000:])
if result.returncode != 0:
    print("Seed script failed:", result.stderr[-2000:])
    sys.exit(1)

print("Seed done, taking screenshots...")

SHOTS_DIR = Path("docs/r41-shots")
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

        async def full(name, path):
            await page.goto(f"{base}{path}",
                            wait_until="networkidle")
            await page.wait_for_timeout(900)
            await page.screenshot(
                path=str(SHOTS_DIR / name), full_page=True)
            print(f"ok {name}")

        await full("world-1440.png",
                   "/world?show=missions,nodes,hardware,compute")
        await full("guide-1440.png", "/guide")
        await full("nodes-1440.png", "/nodes")
        await full("mobile-1440.png", "/mobile")
        await full("craft-1440.png", "/craft")
        await full("symbiosis-1440.png", "/symbiosis")
        await full("presence-1440.png", "/presence")

        await browser.close()


asyncio.run(take_screenshots())
print("All screenshots saved to docs/r41-shots/")
