"""
Publishing helpers (official APIs only):
  - YouTube Data API v3 resumable upload (videos.insert) with OAuth refresh token
  - Telegram Bot API delivery (hand-off for TikTok: you post it from your phone in a few seconds)

Base URLs can be overridden by env vars (used by the offline tests).
"""
import os, subprocess, tempfile, time
from pathlib import Path

import requests

OAUTH_BASE = os.environ.get("OAUTH_BASE", "https://oauth2.googleapis.com")
YT_UPLOAD_BASE = os.environ.get("YT_UPLOAD_BASE", "https://www.googleapis.com")
TG_BASE = os.environ.get("TG_BASE", "https://api.telegram.org")
CHUNK = int(os.environ.get("YT_CHUNK", 8 * 1024 * 1024)) // 262144 * 262144 or 262144   # multiple of 256 KiB


class PublishError(RuntimeError):
    pass


# ───────────────────────── YouTube ─────────────────────────
def yt_access_token(client_id, client_secret, refresh_token):
    r = requests.post(OAUTH_BASE + "/token", data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token"}, timeout=60)
    if r.status_code != 200:
        raise PublishError(f"YouTube token refresh failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


def youtube_upload(path, title, description, tags=None, privacy="private", category="24",
                   ai_disclosure=True, made_for_kids=False, language="en"):
    """Uploads `path` and returns the video id.
    NOTE: until your Google Cloud project passes YouTube's API compliance audit, YouTube forces API uploads to private."""
    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and secret and refresh):
        raise PublishError("Missing YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN")
    token = yt_access_token(cid, secret, refresh)
    size = Path(path).stat().st_size
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": (tags or [])[:15],
                    "categoryId": category, "defaultLanguage": language, "defaultAudioLanguage": language},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids,
                   "containsSyntheticMedia": bool(ai_disclosure)},
    }
    # 1) start a resumable session
    r = requests.post(YT_UPLOAD_BASE + "/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
                      json=meta, timeout=60)
    if r.status_code != 200 or "Location" not in r.headers:
        raise PublishError(f"YouTube upload session failed ({r.status_code}): {r.text[:400]}")
    session = r.headers["Location"]
    # 2) send the file in chunks (resumable: retries re-ask the server how much it already has)
    offset, retries = 0, 0
    with open(path, "rb") as f:
        while offset < size:
            f.seek(offset)
            data = f.read(CHUNK)
            end = offset + len(data) - 1
            try:
                resp = requests.put(session, data=data, allow_redirects=False, timeout=300,
                                    headers={"Content-Length": str(len(data)), "Content-Type": "video/mp4",
                                             "Content-Range": f"bytes {offset}-{end}/{size}"})
            except requests.RequestException as e:
                retries += 1
                if retries > 6:
                    raise PublishError(f"YouTube upload interrupted: {e}")
                time.sleep(5 * retries)
                offset = _yt_resume_offset(session, size)
                continue
            if resp.status_code in (200, 201):
                vid = resp.json().get("id")
                if not vid:
                    raise PublishError("YouTube upload finished but returned no video id")
                return vid
            if resp.status_code == 308:
                rng = resp.headers.get("Range")
                offset = int(rng.split("-")[-1]) + 1 if rng else 0
                retries = 0
                continue
            if resp.status_code in (500, 502, 503, 504):
                retries += 1
                if retries > 6:
                    raise PublishError(f"YouTube upload failed ({resp.status_code})")
                time.sleep(5 * retries)
                offset = _yt_resume_offset(session, size)
                continue
            raise PublishError(f"YouTube upload failed ({resp.status_code}): {resp.text[:400]}")
    raise PublishError("YouTube upload ended without a response")


def youtube_stats(ids):
    """views / likes of our videos (used to learn which videos work)."""
    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    token = yt_access_token(cid, secret, refresh)
    out = {}
    for i in range(0, len(ids), 50):
        r = requests.get(YT_UPLOAD_BASE + "/youtube/v3/videos", params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                         headers={"Authorization": "Bearer " + token}, timeout=60)
        if r.status_code != 200:
            raise PublishError(f"YouTube stats failed ({r.status_code}): {r.text[:200]}")
        for it in r.json().get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0))}
    return out


def youtube_status(vid):
    """The privacy YouTube actually gave the video (it can force 'private' if the API project is locked)."""
    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    token = yt_access_token(cid, secret, refresh)
    r = requests.get(YT_UPLOAD_BASE + "/youtube/v3/videos", params={"part": "status", "id": vid},
                     headers={"Authorization": "Bearer " + token}, timeout=60)
    items = r.json().get("items") or [] if r.status_code == 200 else []
    return (items[0].get("status") or {}).get("privacyStatus") if items else None


def _yt_resume_offset(session, size):
    r = requests.put(session, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"}, allow_redirects=False, timeout=60)
    if r.status_code == 308:
        rng = r.headers.get("Range")
        return int(rng.split("-")[-1]) + 1 if rng else 0
    return 0


# ───────────────────────── Telegram ─────────────────────────
def _shrink(path, limit_mb=48):
    """Telegram bots can send files up to 50 MB: re-encode if needed."""
    if Path(path).stat().st_size <= limit_mb * 1024 * 1024:
        return path
    out = str(Path(tempfile.mkdtemp()) / "tg.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-c:v", "libx264", "-preset", "veryfast",
                    "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "6000k", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", out], check=True)
    return out


def telegram_message(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False
    r = requests.post(f"{TG_BASE}/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=60)
    return r.status_code == 200


def telegram_send_video(path, caption):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        raise PublishError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    p = _shrink(path)
    with open(p, "rb") as f:
        r = requests.post(f"{TG_BASE}/bot{tok}/sendVideo", data={"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"},
                          files={"video": ("legend.mp4", f, "video/mp4")}, timeout=600)
    if r.status_code != 200:
        raise PublishError(f"Telegram sendVideo failed ({r.status_code}): {r.text[:300]}")
    return True
