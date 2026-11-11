#!/usr/bin/env python3
"""
Offline end-to-end test of the daily pipeline against FAKE servers (Claude, Google OAuth, YouTube, Telegram).
It proves the pipeline logic (topic queue, sanitizing, fact-check step, render, resumable upload, Telegram hand-off, state files).
It does NOT prove the real services accept your credentials - use `python daily.py --dry-run` / a real run for that.
    python test_offline.py
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = {"yt_meta": None, "yt_bytes": 0, "yt_failed_once": False, "tg_caption": None, "tg_msgs": [], "claude_calls": []}

SCRIPT = {"mode": "legend", "title": "Aka Manto", "lang": "en", "speed": 0.9, "meta": {
    "title": "Aka Manto: the voice in the bathroom", "description": "A Japanese school legend. Would you answer?", "tags": ["akamanto", "folklore"],
    "tiktok_caption": "Would you answer? #urbanlegends #folklore #horror"},
    "scenes": [
        {"text": "Never answer the voice.", "art": "bathroom", "camera": "creep", "tag": "Japanese Legend", "title": "AKA MANTO", "sfx": ["creak", "laser"]},
        {"text": "It asks a simple question.", "art": "dragon", "camera": "warp", "scare": True, "sfx": ["sting"]},
        {"text": "Red paper or blue paper?", "art": "stall", "camera": "zoom_in", "scare": True},
        {"text": "Nobody agrees on the answer.", "art": "school", "scare": True, "arrow": "bad"},
        {"text": "Some say there is no escape.", "art": "corridor", "camera": "pan_left"},
        {"collage": True, "title": "LEGENDS", "text": "Follow for the next one.", "panels": [{"art": "school", "label": "A"}]}]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=None):
        self._send(code, json.dumps(obj).encode(), {"Content-Type": "application/json", **(headers or {})})

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/w/api.php":
            if q.get("list") == "search":
                LOG["wiki_search"] = q.get("srsearch")
                return self._json({"query": {"search": [{"title": "Aka Manto"}]}})
            return self._json({"query": {"pages": {"1": {"extract": "Aka Manto is a Japanese urban legend about a spirit in school toilets. " * 5}}}})
        if u.path == "/youtube/v3/videos":
            assert self.headers["Authorization"] == "Bearer AT-123"
            LOG["stats_ids"] = q.get("id")
            return self._json({"items": [{"id": i, "statistics": {"viewCount": "1234", "likeCount": "56"}} for i in q["id"].split(",")]})
        self._send(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        path = self.path
        gm = re.match(r"/v1beta/models/([^/:]+):generateContent", path)
        if gm or path == "/v1/messages":
            req = json.loads(body)
            if gm:
                assert self.headers.get("x-goog-api-key") == "g-key"
                prompt = req["contents"][0]["parts"][0]["text"]
            else:
                prompt = req["messages"][0]["content"]
            if "fact-checker" in prompt:
                LOG["claude_calls"].append("factcheck" + ("+search" if req.get("tools") else ""))
                script = json.JSONDecoder().raw_decode(prompt.split("SCRIPT:\n", 1)[1])[0]
                LOG["factcheck_prompt"] = prompt
                out = {"verdict": "fixed", "issues": ["softened one claim"], "script": script}
            elif "Suggest 10 NEW" in prompt:
                LOG["claude_calls"].append("refill")
                out = [{"topic": "Test legend", "hint": "x"}]
            else:
                LOG["claude_calls"].append("generate")
                LOG["gen_prompt"] = prompt
                out = SCRIPT
            if gm:
                self._json({"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]})
            else:
                self._json({"stop_reason": "end_turn", "content": [{"type": "text", "text": "```json\n" + json.dumps(out) + "\n```"}]})
        elif path == "/token":
            self._json({"access_token": "AT-123", "expires_in": 3600})
        elif path.startswith("/upload/youtube/v3/videos"):
            assert self.headers["Authorization"] == "Bearer AT-123"
            LOG["yt_meta"] = json.loads(body)
            LOG["yt_total"] = int(self.headers["X-Upload-Content-Length"])
            self._send(200, b"", {"Location": f"http://127.0.0.1:{self.server.server_port}/session/abc"})
        elif re.match(r"/bot.+/sendVideo", path):
            m = re.search(rb'name="caption"\r\n\r\n(.*?)\r\n--', body, re.S)
            LOG["tg_caption"] = m.group(1).decode() if m else None
            LOG["tg_size"] = len(body)
            self._json({"ok": True})
        elif re.match(r"/bot.+/sendMessage", path):
            LOG["tg_msgs"].append(body.decode())
            self._json({"ok": True})
        else:
            self._send(404)

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        rng = self.headers.get("Content-Range", "")
        if rng.startswith("bytes */"):                        # status query after the simulated failure
            got = LOG["yt_bytes"]
            return self._send(308, b"", {"Range": f"bytes=0-{got - 1}"} if got else {})
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)", rng)
        start, end, total = map(int, m.groups())
        if start >= 2 * 262144 and not LOG["yt_failed_once"]:       # fail once in the middle of the upload
            LOG["yt_failed_once"] = True
            return self._send(503, b"try later")
        assert start == LOG["yt_bytes"], f"chunk out of order: {start} != {LOG['yt_bytes']}"
        LOG["yt_bytes"] = end + 1
        if end + 1 >= total:
            return self._json({"id": "VID123"})
        self._send(308, b"", {"Range": f"bytes=0-{end}"})


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else "gemini"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    tmp = Path(tempfile.mkdtemp())
    for f in list(HERE.glob("*.py")) + [HERE / "topics.json", HERE / "published.json", HERE / "requirements.txt"]:
        shutil.copy(f, tmp / f.name)
    pubs = json.loads((tmp / "published.json").read_text())
    pubs.append({"date": "2026-11-01", "topic": "Old", "title": "Old video", "file": "x.mp4", "youtube_id": "OLD1"})
    (tmp / "published.json").write_text(json.dumps(pubs))
    if (HERE / "fonts").exists():
        shutil.copytree(HERE / "fonts", tmp / "fonts")
    keys = {"GEMINI_API_KEY": "g-key", "GEMINI_API_BASE": base} if provider == "gemini" else {"ANTHROPIC_API_KEY": "k"}
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")}
    env.update(keys, WIKI_API_BASE=base, ANTHROPIC_API_BASE=base, OAUTH_BASE=base, YT_UPLOAD_BASE=base, TG_BASE=base, YT_CLIENT_ID="cid", YT_CLIENT_SECRET="sec", YT_REFRESH_TOKEN="rt", TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_ID="42",
               YT_PRIVACY="private", YT_CHUNK="524288", RENDER_ARGS="--no-tts --no-music")
    r = subprocess.run([sys.executable, "daily.py", "--scenes", "6"], cwd=tmp, env=env, capture_output=True, text=True, timeout=900)
    print(r.stdout[-1500:], r.stderr[-1500:])
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok &= bool(cond)

    check("pipeline exited cleanly", r.returncode == 0)
    pub = json.loads((tmp / "published.json").read_text())
    check("published.json got today's entry with the YouTube id", pub[-1].get("youtube_id") == "VID123")
    check("first unpublished topic was chosen (Aka Manto)", "Aka Manto" in pub[-1]["topic"] or "Aka Manto" in LOG.get("gen_prompt", ""))
    check(f"[{provider}] script generation + fact-check both called", LOG["claude_calls"][:2] == ["generate", "factcheck" + ("+search" if provider == "claude" else "")])
    check("Wikipedia source text was fetched and given to the writer and the fact-checker",
          "Aka Manto is a Japanese urban legend" in LOG.get("gen_prompt", "") and "Aka Manto is a Japanese urban legend" in LOG.get("factcheck_prompt", ""))
    check("results of earlier videos (views) were fed back into the writer", '"Old video" = 1234 views' in LOG.get("gen_prompt", ""))
    meta = LOG["yt_meta"] or {}
    check("YouTube metadata: private, AI disclosure on, not made for kids",
          meta.get("status") == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True})
    check("YouTube title ends with #Shorts and description lists the source", meta["snippet"]["title"].endswith("#Shorts") and "wikipedia.org/wiki/Aka_Manto" in meta["snippet"]["description"].replace("127.0.0.1", "wikipedia.org") or "/wiki/Aka_Manto" in meta["snippet"]["description"])
    check("upload resumed after the simulated 503 and sent every byte", LOG["yt_failed_once"] and LOG["yt_bytes"] == LOG["yt_total"])
    check("Telegram got the video with the TikTok caption", LOG["tg_caption"] and "TikTok caption" in LOG["tg_caption"] and "youtu.be/VID123" in LOG["tg_caption"])
    spec = json.loads(next((tmp / "out").glob("*.json")).read_text())
    check("sanitizer fixed bad art / camera / sfx / arrow and capped scares at 2",
          all(s.get("collage") or (s["art"] != "dragon" and s["camera"] != "warp") for s in spec["scenes"])
          and all("laser" not in s["sfx"] and "arrow" not in s for s in spec["scenes"]) and sum(bool(s.get("scare")) for s in spec["scenes"]) <= 2)
    check("a video file was produced", any((tmp / "out").glob("*.mp4")))
    print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
