"""Post-deploy check of both live URLs: password shell only (no plaintext), then unlock and count rows.
Reads the StatiCrypt password from its file; never prints it. Needs playwright + Google Chrome.
Usage: .venv/bin/python scripts/verify_live.py [BASE_URL]"""
import asyncio, re, sys, urllib.request
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://dot2dot123.github.io/g1-invest/"
PW_FILE = "/home/box/agent-data/secrets/danelfin-dashboard-password"
import os
# Extra private patterns (e.g. the owner's full name) can be passed via G1_LEAK_EXTRA so they are never committed here.
LEAK = re.compile(r'g1data|"tick":|"models":|OTW_holdings' + ("|" + os.environ["G1_LEAK_EXTRA"] if os.environ.get("G1_LEAK_EXTRA") else ""))

async def main():
    ok = True
    for path in ("", "otw/"):
        html = urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"Cache-Control": "no-cache"})).read().decode("utf-8", "ignore")
        leak = bool(LEAK.search(html)); ok &= not leak
        print(f"{path or '/'}: {len(html)} bytes, leak pattern found: {leak}")
    pw = open(PW_FILE).read().strip()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        for path in ("", "otw/"):
            pg = await b.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + path, wait_until="domcontentloaded"); await pg.wait_for_timeout(1500)
            locked = await pg.locator("#tbl").count() == 0
            await pg.fill("input[type=password]", pw); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(4000)
            rows = await pg.locator("#tbl tbody tr").count()
            print(f"{path or '/'}: locked before unlock: {locked}, title after: {await pg.title()}, rows: {rows}, page errors: {errs[:3]}")
            ok &= locked and rows > 0 and not errs
        await b.close()
    del pw
    print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)

asyncio.run(main())
