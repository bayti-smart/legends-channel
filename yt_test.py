"""
End-to-end check of the YouTube link: uploads a 3-second black test clip as UNLISTED, reads back the status YouTube gave it,
then deletes it. If YouTube answers 'private' although we asked 'unlisted', the API project is still locked (needs Google's audit).
"""
import os, subprocess, sys

import requests

import publishers as pub

subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3:r=30", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "test.mp4"], check=True)
vid = pub.youtube_upload("test.mp4", "API test - safe to delete", "Automated connection test.", ["test"], privacy="unlisted")
print(f"::notice title=Upload::test video uploaded: {vid}")
tok = pub.yt_access_token(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN"])
H = {"Authorization": "Bearer " + tok}
r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "status,snippet", "id": vid}, headers=H, timeout=60).json()
it = (r.get("items") or [{}])[0]
st = it.get("status", {})
print(f"::notice title=Status::asked unlisted, YouTube set privacyStatus={st.get('privacyStatus')} uploadStatus={st.get('uploadStatus')} madeForKids={st.get('selfDeclaredMadeForKids')} channel={it.get('snippet', {}).get('channelTitle')}")
d = requests.delete("https://www.googleapis.com/youtube/v3/videos", params={"id": vid}, headers=H, timeout=60)
print(f"::notice title=Cleanup::test video deleted (HTTP {d.status_code})")
try:
    s = pub.youtube_stats([vid])
    print(f"::notice title=Stats::stats call works")
except Exception as e:
    print(f"::notice title=Stats::{type(e).__name__}")
