"""
Fill the app's "How it works" section with every view's saved Cypher, read from views/cricket.yml,
so the explanation cannot drift from what runs. Re-run after any change to a view.

    python3 scripts/inject_how_it_works.py
"""
import html
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps" / "county-cricket.html"

views = yaml.safe_load((ROOT / "views" / "cricket.yml").read_text())
blocks = []
for v in views:
    params = v.get("params") or {}
    plist = ", ".join(f"{k}: {p.get('type', 'string')} = {p.get('default')!r}" for k, p in params.items()) or "no parameters"
    blocks.append(
        f"<details data-view=\"{html.escape(v['name'])}\"><summary><code>{html.escape(v['name'])}</code> — {html.escape(v['description'].strip())}</summary>"
        f"<p class=\"sub\">Parameters: {html.escape(plist)}</p><pre>{html.escape(v['cypher'].strip())}</pre></details>"
    )
src = APP.read_text()
new = re.sub(r"<!-- VIEWS:BEGIN -->.*?<!-- VIEWS:END -->", "<!-- VIEWS:BEGIN -->\n" + "\n".join(blocks) + "\n<!-- VIEWS:END -->", src, flags=re.S)
APP.write_text(new)
print(f"injected {len(blocks)} views")
