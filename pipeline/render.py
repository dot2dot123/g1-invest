"""Render cleartext pages into build/clear/<output_path>index.html (gitignored), one per page in config/users.json.
Encryption happens in scripts/encrypt-pages.sh. Usage: python render.py [--page SLUG]"""
import sys
from common import *
from build_site import load_config
W = ROOT / "web"

def render(cfg):
    html = (W / "template.html").read_text()
    data = (ROOT / "build" / "data" / f"page_{cfg['slug']}.json").read_text().replace("</", "<\\/")
    html = (html.replace("__TITLE__", cfg["title"]).replace("__H1__", cfg.get("h1", cfg["title"])).replace("__PAGE__", cfg["slug"])
                .replace("__CSS__", (W / "style.css").read_text()).replace("__JS__", (W / "app.js").read_text()).replace("__DATA__", data))
    out = ROOT / "build" / "clear" / cfg["output_path"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(html)
    print("rendered", cfg["slug"], "->", out.relative_to(ROOT), len(html) // 1024, "KB")

if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
    for c in load_config():
        if only in (None, c["slug"]): render(c)
