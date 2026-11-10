"""Render cleartext pages into build/clear (gitignored). Encryption happens in scripts/encrypt-pages.sh."""
from common import *
W = ROOT / "web"
def render(page, data_file, out, title, h1):
    html = (W / "template.html").read_text()
    data = (ROOT / "build" / "data" / data_file).read_text().replace("</", "<\\/")
    html = (html.replace("__TITLE__", title).replace("__H1__", h1).replace("__PAGE__", page)
                .replace("__CSS__", (W / "style.css").read_text()).replace("__JS__", (W / "app.js").read_text())
                .replace("__DATA__", data))
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(html)
    print("rendered", out, len(html) // 1024, "KB")
if __name__ == "__main__":
    c = ROOT / "build" / "clear"
    render("main", "main.json", c / "index.html", "G1 · Gary A", "G1 · multi-horizon stock predictor")
    render("otw", "otw.json", c / "otw" / "index.html", "G1 · OTW · Gary A", "G1 · OTW & OTW #2")
