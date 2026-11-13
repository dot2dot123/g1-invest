"""Post-deploy check of every configured page (config/users.json): password shell only (no plaintext), then unlock
with that page's own password file and count table rows. Never prints a password. Needs playwright + Google Chrome.
Usage: .venv/bin/python scripts/verify_live.py [BASE_URL]"""
import asyncio, os, re, sys, urllib.request
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
from build_site import load_config
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://dot2dot123.github.io/g1-invest/"
# Extra private patterns (e.g. the owner's full name) can be passed via G1_LEAK_EXTRA so they are never committed here.
LEAK = re.compile(r'g1data|"rows":|"tmeta":|"books":|"tick":|"models":|OTW_holdings' + ("|" + os.environ["G1_LEAK_EXTRA"] if os.environ.get("G1_LEAK_EXTRA") else ""))

async def main():
    ok = True; pages = load_config()
    for c in pages:
        html = urllib.request.urlopen(urllib.request.Request(BASE + c["output_path"], headers={"Cache-Control": "no-cache"})).read().decode("utf-8", "ignore")
        leak = bool(LEAK.search(html)); ok &= not leak
        print(f"{c['slug']} /{c['output_path']}: {len(html)} bytes, leak pattern found: {leak}")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        for c in pages:
            pw = open(c["password_file"]).read().strip()
            pg = await b.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + c["output_path"], wait_until="domcontentloaded"); await pg.wait_for_timeout(1500)
            locked = await pg.locator("#tbl").count() == 0
            await pg.fill("input[type=password]", pw); del pw
            await pg.keyboard.press("Enter"); await pg.wait_for_timeout(6000)
            rows = await pg.locator("#tbl tbody tr").count(); wx = await pg.locator("#weather b").count()
            print(f"{c['slug']}: locked before unlock: {locked}, title after: {await pg.title()}, rows: {rows}, weather banner: {wx > 0}, page errors: {errs[:3]}")
            ok &= locked and rows > 0 and wx > 0 and not errs
        await b.close()
    print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)

asyncio.run(main())
