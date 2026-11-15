#!/usr/bin/env python3
"""
Runs in GitHub Actions (workflow yt-auth.yml). Links the NEW YouTube channel without you copying anything:
  1) asks Google for a device code,
  2) sends the link + code to your Telegram,
  3) waits until you approve on your phone,
  4) prints the refresh token ENCRYPTED with a public key (only the setup owner can decrypt it) and the name of the channel that was authorized.
"""
import base64, os, sys, time

import requests

OAUTH = os.environ.get("OAUTH_BASE") or "https://oauth2.googleapis.com"
API = os.environ.get("YT_UPLOAD_BASE") or "https://www.googleapis.com"
TG = os.environ.get("TG_BASE") or "https://api.telegram.org"
SCOPE = "https://www.googleapis.com/auth/youtube"
cid, secret = os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"]
pub = os.environ["YT_AUTH_PUBKEY"]


def tell(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        requests.post(f"{TG}/bot{tok}/sendMessage", data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, timeout=30)


r = requests.post(OAUTH + "/device/code", data={"client_id": cid, "scope": SCOPE}, timeout=60)
if r.status_code != 200:
    print(f"::error title=Google::device code request failed ({r.status_code}): {r.text[:300]}")
    tell("❌ فشل بدء ربط يوتيوب: " + r.text[:200])
    sys.exit(1)
d = r.json()
tell("🔐 ربط قناة يوتيوب الجديدة\n\n1) افتح هذا الرابط من الجوال:\n" + d["verification_url"] +
     "\n\n2) أدخل هذا الكود:\n" + d["user_code"] +
     "\n\n3) اختر القناة الجديدة (قناة الأساطير) وليس قناة الأطفال.\n4) إن ظهرت رسالة «Google hasn't verified this app» اضغط Advanced ثم Go to ... ثم Continue / Allow.\n\nالكود صالح لنحو " + str(int(d.get("expires_in", 1800)) // 60) + " دقيقة.")
print("::notice title=Waiting::the link and code were sent to Telegram")
deadline, interval = time.time() + int(d.get("expires_in", 1800)), int(d.get("interval", 5))
tok = None
while time.time() < deadline:
    time.sleep(interval)
    j = requests.post(OAUTH + "/token", timeout=60, data={"client_id": cid, "client_secret": secret, "device_code": d["device_code"],
                                                         "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).json()
    if "refresh_token" in j:
        tok = j
        break
    err = j.get("error")
    if err == "slow_down":
        interval += 5
    elif err != "authorization_pending":
        print(f"::error title=Google::authorization failed: {j}")
        tell("❌ فشل الربط: " + str(j)[:200])
        sys.exit(1)
if not tok:
    print("::error title=Google::timed out waiting for approval")
    tell("⏳ انتهت مهلة الربط دون موافقة. أخبرني لأبدأ من جديد.")
    sys.exit(1)

ch = requests.get(API + "/youtube/v3/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=60)
name = "?"
if ch.status_code == 200 and ch.json().get("items"):
    it = ch.json()["items"][0]
    name = f'{it["snippet"]["title"]} ({it["id"]})'
from nacl import encoding, public
enc = base64.b64encode(public.SealedBox(public.PublicKey(pub.encode(), encoding.Base64Encoder())).encrypt(tok["refresh_token"].encode())).decode()
print(f"::notice title=Channel authorized::{name}")
print(f"::notice title=YT_TOKEN_ENC::{enc}")
tell(f"✅ تم الربط بقناة: {name}")
