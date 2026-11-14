#!/usr/bin/env python3
"""
Finds which spelling of a hand-read Telegram bot token is valid (I/l and O/0 look alike in screenshots),
then finds the chat id of whoever pressed Start on the bot. Prints only the variant NUMBER and the bot name, never the token.
Run in GitHub Actions (workflow tg-setup.yml) because api.telegram.org may be unreachable from other sandboxes.
"""
import itertools, os, sys

import requests

raw = os.environ["TG_TOKEN_RAW"].strip()
head, _, tail = raw.partition(":")
amb = {"I": "Il", "l": "Il", "O": "O0", "0": "O0"}
opts = [amb.get(c, c) for c in tail]
pos = [i for i, o in enumerate(opts) if len(o) > 1]


def variants():
    for n, choice in enumerate(itertools.product(*[opts[i] for i in pos])):
        t = list(tail)
        for i, c in zip(pos, choice):
            t[i] = c
        yield n, head + ":" + "".join(t)


found = None
for n, tok in variants():
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20)
    except requests.RequestException as e:
        print(f"::error title=Telegram::cannot reach Telegram: {type(e).__name__}")
        sys.exit(1)
    if r.status_code == 200 and r.json().get("ok"):
        found = (n, tok, r.json()["result"]["username"])
        break
if not found:
    print(f"::error title=Telegram token::none of the {sum(1 for _ in variants())} spellings is valid")
    sys.exit(1)
n, tok, name = found
print(f"::notice title=Telegram token::valid spelling is variant #{n} of bot @{name}")
u = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=30).json().get("result", [])
chats = {}
for item in u:
    m = item.get("message") or item.get("my_chat_member") or {}
    ch = m.get("chat") or {}
    if ch.get("id") and ch.get("type") == "private":
        chats[ch["id"]] = ch.get("first_name", "")
if chats:
    cid = list(chats)[-1]
    print(f"::notice title=Telegram chat::chat id {cid} ({chats[cid]})")
    s = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": cid, "text": "✅ البوت مربوط ويعمل. ستصلك هنا فيديوهات الأساطير."}, timeout=30)
    print(f"::notice title=Telegram test message::sent={s.status_code == 200}")
else:
    print("::warning title=Telegram chat::no one pressed Start on the bot yet")
