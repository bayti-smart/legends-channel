#!/usr/bin/env python3
"""Offline test of the weekly review against fake Gemini / YouTube / Telegram servers.   python test_weekly_offline.py"""
import datetime, json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = {"tg": [], "prompt": ""}
ANALYSIS = {"summary_ar": "الفيديوهات ذات التحذير في أول جملة حققت مشاهدات أكثر، لكن العينة صغيرة.", "guidance": "Open with a second-person warning. Keep scenes short.",
            "voice_weights": {"am_onyx": 0.95, "bm_george": 0.05}, "hook_weights": {"question": 0.0, "warning": 1.0, "claim": 0.0, "mystery": 0.0},
            "length_weights": {"short": 0.2, "medium": 0.6, "long": 0.2}, "topic_priorities": ["snow yokai"],
            "new_topics": [{"topic": "Yuki-onna sequel: Setsu legends", "hint": "snow yokai documented in folktales"}, {"topic": "Kappa", "hint": "dup"}],
            "visual_ideas_ar": ["إضافة حركة ثلج متساقط", "نغمة موسيقى أخف"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, o, c=200):
        b = json.dumps(o).encode(); self.send_response(c); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/v1beta/models": return self._j({"models": [{"name": "models/gemini-9-flash", "supportedGenerationMethods": ["generateContent"]}]})
        if u.path == "/youtube/v3/videos":
            return self._j({"items": [{"id": i, "statistics": {"viewCount": str(100 * (n + 1)), "likeCount": str(5 * n), "commentCount": str(n)}} for n, i in enumerate(q["id"].split(","))]})
        self._j({}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode()
        if self.path == "/token": return self._j({"access_token": "AT"})
        if re.match(r"/v1beta/models/.+:generateContent", self.path):
            LOG["prompt"] = json.loads(body)["contents"][0]["parts"][0]["text"]
            return self._j({"candidates": [{"content": {"parts": [{"text": json.dumps(ANALYSIS)}]}}]})
        if "sendMessage" in self.path:
            from urllib.parse import unquote_plus
            LOG["tg"].append(unquote_plus(body)); return self._j({"ok": True})
        self._j({}, 404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    tmp = Path(tempfile.mkdtemp())
    for f in list(HERE.glob("*.py")) + [HERE / "topics.json", HERE / "playbook.json"]:
        shutil.copy(f, tmp / f.name)
    now = datetime.datetime.now(datetime.timezone.utc)
    pubs = [{"date": "x", "published_at": (now - datetime.timedelta(days=4 + i)).isoformat(timespec="minutes"), "topic": f"T{i}", "title": f"Video {i}", "youtube_id": f"V{i}",
             "voice": "am_onyx" if i % 2 else "bm_george", "hook_style": ["question", "warning", "claim", "mystery"][i % 4], "length": "medium", "scenes": 11, "duration_s": 60, "hook": "h", "arts": ["snow"]} for i in range(8)]
    (tmp / "published.json").write_text(json.dumps(pubs))
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY",)}
    env.update(GEMINI_API_KEY="g", GEMINI_API_BASE=base, OAUTH_BASE=base, YT_UPLOAD_BASE=base, TG_BASE=base, YT_CLIENT_ID="c", YT_CLIENT_SECRET="s", YT_REFRESH_TOKEN="r",
               TELEGRAM_BOT_TOKEN="1:x", TELEGRAM_CHAT_ID="9", GEMINI_MODEL="gemini-9-flash")
    r = subprocess.run([sys.executable, "weekly.py"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    print(r.stdout[-500:], r.stderr[-500:])
    ok = True
    def check(n, c):
        nonlocal ok; print(("PASS " if c else "FAIL ") + n); ok &= bool(c)
    check("exit 0", r.returncode == 0)
    pb = json.loads((tmp / "playbook.json").read_text())
    check("playbook has guidance", "second-person warning" in pb.get("guidance", ""))
    check("weights are normalized and keep an exploration floor", abs(sum(pb["voice_weights"].values()) - 1) < 0.01 and min(pb["voice_weights"].values()) >= 0.15 and min(pb["hook_weights"].values()) >= 0.1)
    check("winning hook style got the largest weight", max(pb["hook_weights"], key=pb["hook_weights"].get) == "warning")
    topics = json.loads((tmp / "topics.json").read_text())["queue"]
    check("new topic added in front, duplicate (Kappa) not added twice", topics[0]["topic"].startswith("Yuki-onna sequel") and sum(t["topic"].startswith("Kappa") for t in topics) == 1)
    check("snow topics moved ahead of the others", all("snow" in (t["topic"] + t["hint"]).lower() or "yuki" in (t["topic"] + t["hint"]).lower() for t in topics[:2]))
    p2 = json.loads((tmp / "published.json").read_text())
    check("views / comments written back to published.json", p2[0]["views"] == 100 and p2[1]["comments"] == 1)
    check("data (voice, hook style) reached the analyst prompt", '"hook_style": "warning"' in LOG["prompt"] and "views_per_day" in LOG["prompt"])
    check("Arabic report sent to Telegram with the visual ideas", any("تقرير الأسبوع" in t and "ثلج" in t for t in LOG["tg"]))
    # not enough data case
    (tmp / "published.json").write_text(json.dumps(pubs[:2]))
    LOG["tg"].clear()
    r2 = subprocess.run([sys.executable, "weekly.py"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    check("too little data: no analysis, polite message instead", r2.returncode == 0 and any("لا توجد بيانات كافية" in t for t in LOG["tg"]))
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
