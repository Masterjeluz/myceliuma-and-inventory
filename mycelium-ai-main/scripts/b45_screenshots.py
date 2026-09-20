"""Take BIG #45 connections screenshots with Playwright.

Seeds tmp DBs via b45_shots.py, serves them on 127.0.0.1:8897
in a background thread, captures the curated set into
docs/r45-shots/ (desktop 1440 + mobile 390). No real DBs
touched.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

TMP = r"C:\Users\Jelles\AppData\Local\Temp\b45_shots"
PORT = 8897

os.makedirs(TMP, exist_ok=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(TMP, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    TMP, "shots-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b45-shot-operator"

import uvicorn  # noqa: E402
import coordinator.app.main as main_mod  # noqa: E402


def run_server():
    uvicorn.run(main_mod.app, host="127.0.0.1", port=PORT,
                log_level="warning")


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(3)

result = subprocess.run(
    [sys.executable, "scripts/b45_shots.py"],
    capture_output=True, text=True, cwd=".",
    env={**os.environ, "B45_SHOT_TMP": TMP})
print(result.stdout[-2000:])
if result.returncode != 0:
    print("Seed script failed:", result.stderr[-2000:])
    sys.exit(1)

with open(os.path.join(TMP, "shots_ids.json"), encoding="utf-8") as handle:
    ids = json.load(handle)

print("Seed done, taking screenshots...")

SHOTS_DIR = Path("docs/r45-shots")
SHOTS_DIR.mkdir(exist_ok=True)


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

        fin = quote(ids["fin"], safe="")
        await full("connections-detail-1440.png",
                   f"/connections?a=proj_solar&b={fin}")
        await full("world-focused-1440.png",
                   "/world?entity_id=proj_solar")
        await full("world-network-1440.png", "/world")
        await full("world-mobile-390.png", "/world", width=390,
                   height=844)
        await full("mobile-390.png", "/mobile", width=390,
                   height=844)
        await full("guide-1440.png", "/guide")
        await full("morning-1440.png", "/morning")
        await full("campaigns-1440.png", "/campaigns")

        await browser.close()


asyncio.run(take_screenshots())
print("All screenshots saved to docs/r45-shots/")
