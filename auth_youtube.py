#!/usr/bin/env python3
"""
One-time YouTube authorization that works from a phone (OAuth "device flow"): no local web server needed.

  1. In Google Cloud Console create an OAuth client of type "TVs and Limited Input devices".
  2. export YT_CLIENT_ID=...  YT_CLIENT_SECRET=...
  3. python auth_youtube.py   -> open the printed link on your phone, enter the code, approve.
  4. Copy the printed refresh token into the GitHub secret YT_REFRESH_TOKEN.

If Google answers "invalid_scope" use the OAuth Playground fallback described in SETUP_AR.md.
"""
import os, sys, time

import requests

BASE = os.environ.get("OAUTH_BASE", "https://oauth2.googleapis.com")
SCOPE = "https://www.googleapis.com/auth/youtube"       # the youtube.upload scope is not allowed in the device flow


def main():
    cid, secret = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
    if not (cid and secret):
        sys.exit("Set YT_CLIENT_ID and YT_CLIENT_SECRET first")
    r = requests.post(BASE + "/device/code", data={"client_id": cid, "scope": SCOPE}, timeout=60)
    if r.status_code != 200:
        sys.exit(f"device/code failed ({r.status_code}): {r.text}")
    d = r.json()
    print(f"\n1) Open:  {d['verification_url']}\n2) Enter the code:  {d['user_code']}\n   (waiting for you to approve…)\n", flush=True)
    deadline, interval = time.time() + int(d.get("expires_in", 1800)), int(d.get("interval", 5))
    while time.time() < deadline:
        time.sleep(interval)
        t = requests.post(BASE + "/token", timeout=60, data={
            "client_id": cid, "client_secret": secret, "device_code": d["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        j = t.json()
        if "refresh_token" in j:
            print("\n✔ Authorized. Save this as the secret YT_REFRESH_TOKEN:\n\n" + j["refresh_token"] + "\n")
            return
        err = j.get("error")
        if err == "slow_down":
            interval += 5
        elif err not in ("authorization_pending",):
            sys.exit(f"authorization failed: {j}")
    sys.exit("timed out waiting for approval")


if __name__ == "__main__":
    main()
