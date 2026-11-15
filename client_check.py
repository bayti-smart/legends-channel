#!/usr/bin/env python3
"""
Finds the correct spelling of a Client ID / Client secret that was read from a screenshot (o/0, l/1/I, O/0 look alike).
Asks Google itself: a wrong Client ID is refused by /device/code, a wrong secret is refused by /token with 'invalid_client'.
Prints only variant NUMBERS, never the values.
"""
import itertools, os, sys

import requests

BASE = os.environ.get("OAUTH_BASE") or "https://oauth2.googleapis.com"
cid_raw, sec_raw = os.environ["CID_RAW"].strip(), os.environ["CSEC_RAW"].strip()
ID_AMB = {"1": "1l", "l": "1l", "o": "o0", "0": "o0"}
SEC_AMB = {"O": "O0", "0": "O0", "o": "o0", "l": "lI1", "I": "lI1", "1": "lI1", "i": "il"}


def variants(raw, head_len, amb):
    if os.environ.get("EXACT"):
        yield 0, raw
        return
    head, tail = raw[:head_len], raw[head_len:]
    opts = [amb.get(c, c) for c in tail]
    pos = [i for i, o in enumerate(opts) if len(o) > 1]
    for n, choice in enumerate(itertools.product(*[opts[i] for i in pos])):
        t = list(tail)
        for i, c in zip(pos, choice):
            t[i] = c
        yield n, head + "".join(t)


good_id = None
for n, cid in variants(cid_raw, cid_raw.index("-") + 1, ID_AMB):
    r = requests.post(BASE + "/device/code", data={"client_id": cid, "scope": "https://www.googleapis.com/auth/youtube"}, timeout=30)
    if r.status_code == 200:
        good_id = (n, cid)
        break
    if r.json().get("error") != "invalid_client":
        print(f"::warning title=Client ID::unexpected answer {r.status_code}: {r.text[:150]}")
if not good_id:
    print("::error title=Client ID::none of the spellings is accepted by Google")
    sys.exit(1)
print(f"::notice title=Client ID::valid spelling is variant #{good_id[0]}")
good_sec = None
for n, sec in variants(sec_raw, sec_raw.index("-") + 1, SEC_AMB):
    r = requests.post(BASE + "/token", data={"client_id": good_id[1], "client_secret": sec, "refresh_token": "dummy", "grant_type": "refresh_token"}, timeout=30)
    if r.json().get("error") != "invalid_client":
        good_sec = (n, sec)
        print(f"::notice title=Client secret::valid spelling is variant #{n} (server answer: {r.json().get('error')})")
        break
if not good_sec:
    print("::error title=Client secret::none of the spellings is accepted. Please copy the secret again as TEXT.")
    sys.exit(1)
