"""Take BIG #44 world screenshots with Playwright.

Seeds tmp DBs via b44_shots.py, serves them on 127.0.0.1:8896
in a background thread, captures the curated set into
docs/r44-shots/ (desktop 1440 + world mobile 390). No real
DBs touched.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TMP = r"C:\Users\Jelles\AppData\Local\Temp\b44_shots"
PORT = 8896

os.makedirs(TMP, exist_ok=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(TMP, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    TMP, "shots-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b44-shot-operator"

import uvicorn  # noqa: E402
import coordinator.app.main as main_mod  # noqa: E402


def run_server():
    uvicorn.run(main_mod.app, host="127.0.0.1", port=PORT,
                log_level="warning")


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(3)

result = subprocess.run(
    [sys.executable, "scripts/b44_shots.py"],
    capture_output=True, text=True, cwd=".",
    env={**os.environ, "B44_SHOT_TMP": TMP})
print(result.stdout[-2000:])
if result.returncode != 0:
    print("Seed script failed:", result.stderr[-2000:])
    sys.exit(1)

print("Seed done, taking screenshots...")

SHOTS_DIR = Path("docs/r44-shots")
SHOTS_DIR.mkdir(exist_ok=True)

import asyncio  # noqa: E402


async def take_screenshots():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge",
                                          headless=True)
        base = f"http://127.0.0.1:{PORT}"

        async def full(name, path, width=1440, height=900):
            page = await browser.new_page(
                viewport={"width": width, "height": height})
            await page.goto(f"{base}{path}",
                            wait_until="networkidle")
            await page.wait_for_timeout(900)
            await page.screenshot(
                path=str(SHOTS_DIR / name), full_page=True)
            print(f"ok {name}")
            await page.close()

        await full("world-1440.png",
                   "/world?show=missions,nodes,hardware,compute")
        await full("world-mobile-390.png", "/world", width=390,
                   height=844)
        await full("campaign-1440.png", "/campaigns")
        await full("craft-1440.png", "/craft")
        await full("symbiosis-1440.png", "/symbiosis")
        await full("nodes-1440.png", "/nodes")
        await full("hardware-1440.png", "/hardware")
        await full("presence-1440.png", "/presence")
        await full("guide-1440.png", "/guide")
        await full("morning-1440.png", "/morning")

        await browser.close()


asyncio.run(take_screenshots())
print("All screenshots saved to docs/r44-shots/")
