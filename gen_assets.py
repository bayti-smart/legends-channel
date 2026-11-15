"""Generates the images listed in assets_prompts.json (free Pollinations service) - used for channel pictures."""
import hashlib, json, os, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import legend

STYLE = os.environ.get("ASSET_STYLE", "")
out = Path("assets_out")
out.mkdir(exist_ok=True)
ok = 0
items = json.load(open("assets_prompts.json", encoding="utf-8"))
for i, it in enumerate(items):
    p = out / f"{it['name']}.png"
    good, why = False, ""
    for attempt in range(2):
        good, why = legend._fetch_pollinations(it["prompt"] + STYLE, p, 1000 + i * 13 + attempt * 7, it.get("w", 1024), it.get("h", 1024))
        if good:
            break
    ok += good
    print(f"::notice title=Image {it['name']}::{'OK' if good else 'FAILED'} {why}")
    time.sleep(6)
print(f"::notice title=Summary::{ok}/{len(items)} images generated")
