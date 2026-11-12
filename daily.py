#!/usr/bin/env python3
"""
Daily pipeline for the legends channel (no human in the loop):

  pick a legend -> write the script (Claude) -> fact-check it with web search (Claude) -> sanitize ->
  render the video -> upload to YouTube -> send the video + TikTok caption to your Telegram -> save state.

Run:  python daily.py            (real run)
      python daily.py --dry-run  (does everything except uploading / sending)
Env:  GEMINI_API_KEY (free) or ANTHROPIC_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
      YT_PRIVACY (private|unlisted|public, default private), IMAGE_API_KEY / IMAGE_PROVIDER (optional, better art)
"""
import argparse, datetime, json, os, random, re, subprocess, sys, time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_reel as mr          # noqa: E402  (prompts live there)
import legend                   # noqa: E402
import legend_art as la         # noqa: E402
import publishers as pub        # noqa: E402

legend.bind(mr)
TOPICS, PUBLISHED, OUT = HERE / "topics.json", HERE / "published.json", HERE / "out"
API = os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL", "web_search_20250305")
VALID_ART = set(la.ARTS) | {"corridor_figure", "bathroom_empty", "street_figure"}
VALID_SFX = {"knock", "sting", "whisper", "creak", "boom"}
ART_CYCLE = ["school", "corridor", "bathroom", "street", "forest", "mask", "stall", "eyes"]
BASE_TAGS = ["#Shorts", "#UrbanLegends", "#Folklore", "#Horror"]


class Rejected(Exception):
    pass


class Blocked(Rejected):
    """The AI provider's safety filter refused the prompt: skip this topic."""


# ───────────────────────── LLM (free Gemini key preferred, Claude optional) ─────────────────────────
GEMINI_BASE = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com")
GEMINI_MODELS = [m.strip() for m in os.environ.get("GEMINI_MODEL", "gemini-2.5-flash,gemini-3.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]


_models_cache = []


def gemini_models(key):
    """Models this key can use, newest flash first (Google retires models often, so we ask instead of hard-coding)."""
    if _models_cache:
        return _models_cache
    pinned = [m.strip() for m in os.environ.get("GEMINI_MODEL", "").split(",") if m.strip()]
    found = []
    try:
        r = requests.get(f"{GEMINI_BASE}/v1beta/models", params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=60)
        for m in r.json().get("models", []):
            name = m.get("name", "").replace("models/", "")
            if "generateContent" in m.get("supportedGenerationMethods", []) and name.startswith("gemini-") and "flash" in name \
                    and not any(x in name for x in ("image", "tts", "live", "audio", "embedding", "thinking", "robotics", "computer", "learnlm")):
                ver = [int(x) for x in re.findall(r"\d+", name.split("flash")[0])] or [0]
                found.append((ver, "lite" not in name, "preview" not in name and "exp" not in name, name))
    except Exception as e:
        print("  (could not list Gemini models:", e, ")")
    found.sort(reverse=True)
    names = pinned + [n for *_, n in found if n not in pinned] + [m for m in GEMINI_MODELS if m not in pinned]
    _models_cache.extend(dict.fromkeys(names))
    print("  Gemini models to try:", _models_cache[:6])
    return _models_cache


def gemini(prompt, max_tokens=8192, json_mode=True):
    key = os.environ["GEMINI_API_KEY"]
    errors = []
    for model in gemini_models(key)[:8]:             # if a model is gone / rate limited, try the next one
        for attempt in range(3):
            gen = {"maxOutputTokens": max_tokens, "temperature": 0.8}
            if json_mode:
                gen["responseMimeType"] = "application/json"
            r = requests.post(f"{GEMINI_BASE}/v1beta/models/{model}:generateContent", timeout=300, json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen},
                headers={"x-goog-api-key": key, "content-type": "application/json"})
            if r.status_code == 200:
                data = r.json()
                parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                if parts:
                    return "".join(p.get("text", "") for p in parts)
                block = (data.get("promptFeedback") or {}).get("blockReason")
                if block:
                    raise Blocked(f"the safety filter blocked this topic ({block})")
                errors.append(f"{model}: empty answer ({str(data.get('promptFeedback'))[:80]})")
                break
            body = " ".join(r.text.split())[:140]
            errors.append(f"{model}: HTTP {r.status_code} {body}")
            if r.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(15 * (attempt + 1))
                continue
            break
    raise RuntimeError("Gemini failed: " + " || ".join(errors)[:1500])


def claude(prompt, tools=None, max_tokens=8000):
    key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("Set ANTHROPIC_API_KEY")
    messages = [{"role": "user", "content": prompt}]
    for _ in range(6):                      # a few rounds: server-side tools can pause the turn
        body = {"model": MODEL, "max_tokens": max_tokens, "messages": messages}
        if tools:
            body["tools"] = tools
        for attempt in range(4):
            r = requests.post(API + "/v1/messages", timeout=420, json=body,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            if r.status_code == 200:
                break
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(f"Claude API {r.status_code}: {r.text[:400]}")
        else:
            raise RuntimeError("Claude API unavailable")
        data = r.json()
        if data.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": data["content"]})
            continue
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    raise RuntimeError("Claude did not finish")


def llm(prompt, search=False, max_tokens=8000):
    if os.environ.get("GEMINI_API_KEY"):
        return gemini(prompt, max_tokens)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return claude(prompt, tools=[{"type": SEARCH_TOOL, "name": "web_search", "max_uses": 8}] if search else None, max_tokens=max_tokens)
    sys.exit("Set GEMINI_API_KEY (free, from aistudio.google.com) or ANTHROPIC_API_KEY")


# ───────────────────────── sources (Wikipedia: free, no key) ─────────────────────────
WIKI = os.environ.get("WIKI_API_BASE", "https://en.wikipedia.org")
UA = {"User-Agent": "legend-channel-bot/1.0 (educational folklore videos)"}


def gather_sources(topic, limit=3, chars=5500):
    q = re.sub(r"\(.*?\)", "", topic).strip()
    r = requests.get(WIKI + "/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "list": "search", "srsearch": q + " legend OR folklore OR yokai", "format": "json", "srlimit": limit})
    titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
    texts, urls = [], []
    for t in titles[:limit]:
        r2 = requests.get(WIKI + "/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "plain", "titles": t, "format": "json", "redirects": 1})
        page = next(iter(r2.json().get("query", {}).get("pages", {}).values()), {})
        ext = (page.get("extract") or "")[:chars]
        if ext.strip():
            texts.append(f"## {t}\n{ext}")
            urls.append(WIKI + "/wiki/" + t.replace(" ", "_"))
    return "\n\n".join(texts), urls


def extract_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON in model output")
    return json.loads(text[i:j + 1])


def extract_json_list(text):
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("["), text.rfind("]")
    return json.loads(text[i:j + 1])


# ───────────────────────── state ─────────────────────────
def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_topic(topics, published):
    done = {p["topic"].lower() for p in published}
    for t in topics["queue"]:
        if t["topic"].lower() not in done and t.get("status") != "rejected":
            return t
    return None


def refill_topics(topics, published):
    have = [t["topic"] for t in topics["queue"]] + [p["topic"] for p in published]
    txt = llm("Suggest 10 NEW well-documented urban legends or folklore creatures (mostly Japanese, some from other cultures) for short horror-folklore videos. "
                 "Only choose subjects with solid, documented sources; avoid gore, real tragedies and anything about suicide or self-harm. "
                 f"Do NOT repeat any of these: {have}. "
                 'Return ONLY a JSON list: [{"topic": "...", "hint": "one sentence on what is well documented about it"}]')
    new = extract_json_list(txt)
    topics["queue"] += [{"topic": str(n["topic"]), "hint": str(n.get("hint", ""))} for n in new if n.get("topic")]
    return topics


# ───────────────────────── script ─────────────────────────
EXTRA = """
Also add a top-level key "meta": {{"title": "catchy YouTube title, max 80 chars, no emojis", "description": "2-3 sentences + a one-line question for comments",
"tags": ["8-12 plain tags"], "tiktok_caption": "caption under 150 chars with 3-4 hashtags"}}.
Topic notes: {hint}
Performance of our earlier videos (learn which hooks, topics and structures got more views and lean into what works - never copy an old video): {perf}
Vary the structure from episode to episode (different hook type, different scene order, different closing line)."""

FACTCHECK = """You are a strict fact-checker and editor for a short folklore video script (JSON below).
1. Verify EVERY factual claim (dates, places, names, rules of the legend, numbers, who documented it) against the SOURCE MATERIAL given after the script (and web search if you have it).
2. Keep a claim only if the sources support it. Rewrite unsupported or disputed claims as "some versions say" / "some say", or delete them.
3. Make sure nothing is graphic, gory, hateful, or about suicide or self-harm, and nothing is presented as real tragedy sensationalized for shock. Dread must come from atmosphere.
4. Keep the exact JSON structure and keys of the script (scenes, art, camera, sfx, title, label, arrow, collage, panels, meta ...). You may reword narration. Keep the number of scenes within +/-1.
5. Return ONLY JSON: {{"verdict": "ok" | "fixed" | "reject", "issues": ["short strings"], "script": <the full corrected script>}}.
   Use "reject" only if the topic cannot be told accurately and safely.

SCRIPT:
{script}
"""


def sanitize(spec, narrator):
    spec["mode"] = "legend"
    spec["lang"] = "en"
    spec["speed"] = min(1.0, max(0.8, float(spec.get("speed", 0.9) or 0.9)))
    spec["voices"] = {"narrator": narrator}
    out, scares = [], 0
    for i, sc in enumerate(spec.get("scenes", [])):
        sc["text"] = str(sc.get("text", "")).strip()
        if not sc["text"]:
            continue
        if sc.get("collage"):
            panels = [p for p in (sc.get("panels") or []) if isinstance(p, dict)]
            for k, p in enumerate(panels):
                if p.get("art") not in VALID_ART:
                    p["art"] = ART_CYCLE[(i + k) % len(ART_CYCLE)]
                p["label"] = str(p.get("label", ""))[:14]
            while len(panels) < 3:
                panels.append({"art": ART_CYCLE[len(panels) % len(ART_CYCLE)], "label": ""})
            sc["panels"], sc["title"] = panels[:3], str(sc.get("title", "LEGENDS"))[:16]
        else:
            if sc.get("art") not in VALID_ART:
                sc["art"] = ART_CYCLE[i % len(ART_CYCLE)]
            if sc.get("camera") not in legend.MODES:
                sc["camera"] = "creep"
        sc["sfx"] = [s for s in (sc.get("sfx") or []) if isinstance(s, str) and s in VALID_SFX]
        for k in ("title", "label", "tag"):
            if sc.get(k):
                sc[k] = str(sc[k])[:26]
        ar = sc.get("arrow")
        if not (isinstance(ar, (list, tuple)) and len(ar) == 3 and all(isinstance(v, (int, float)) for v in ar)):
            sc.pop("arrow", None)
        lx = sc.get("label_xy")
        if not (isinstance(lx, (list, tuple)) and len(lx) == 2 and all(isinstance(v, (int, float)) for v in lx)):
            sc.pop("label_xy", None)
        kn = sc.get("knocks")
        if kn is not None and not (isinstance(kn, list) and all(isinstance(v, (int, float)) for v in kn)):
            sc.pop("knocks", None)
        if sc.get("scare"):
            scares += 1
            if scares > 2:
                sc["scare"] = False
        sc.pop("image", None)
        out.append(sc)
    if not 6 <= len(out) <= 16:
        raise ValueError(f"script has {len(out)} usable scenes")
    spec["scenes"] = out
    return spec


def generate_script(topic, scenes, narrator, sources_text="", perf=""):
    prompt = (mr.GEN_LEGEND_PROMPT.format(topic=f"{topic['topic']}", n=scenes) + EXTRA.format(hint=topic.get("hint", ""), perf=perf or "no data yet")
              + ("\n\nSOURCE MATERIAL - base every factual claim on this text (or on widely known common knowledge). "
                 "Do not invent dates, names, places or numbers that are not here:\n" + sources_text if sources_text else ""))
    return sanitize(extract_json(llm(prompt)), narrator)


def factcheck(spec, narrator, sources_text=""):
    res = extract_json(llm(FACTCHECK.format(script=json.dumps(spec, ensure_ascii=False)) +
                           ("\n\nSOURCE MATERIAL (your only evidence; a claim that is not supported here must be softened or removed):\n" + sources_text if sources_text else ""),
                           search=True))
    if res.get("verdict") == "reject":
        raise Rejected("; ".join(res.get("issues", [])) or "rejected by fact-check")
    fixed = res.get("script")
    if isinstance(fixed, dict) and fixed.get("scenes"):
        fixed.setdefault("meta", spec.get("meta", {}))
        spec = sanitize(fixed, narrator)
    return spec, res.get("issues", [])


def build_meta(spec, topic, sources):
    m = spec.get("meta") or {}
    title = str(m.get("title") or spec.get("title") or topic["topic"])[:88].strip()
    tags = [str(t).lstrip("#")[:30] for t in (m.get("tags") or [])][:12]
    desc = str(m.get("description") or "").strip()
    if sources:
        desc += "\n\nSources:\n" + "\n".join(sources)
    desc += "\n\nIllustrated and narrated with AI tools.\n" + " ".join(BASE_TAGS)
    cap = str(m.get("tiktok_caption") or f"{title} #urbanlegends #folklore #horror #fyp")[:300]
    return title + " #Shorts", desc, tags, cap


# ───────────────────────── learning from results ─────────────────────────
def refresh_stats(published):
    ids = [p["youtube_id"] for p in published if p.get("youtube_id")][-40:]
    if not ids or not os.environ.get("YT_REFRESH_TOKEN"):
        return ""
    try:
        st = pub.youtube_stats(ids)
    except Exception as e:
        print("  (could not read YouTube stats:", e, ")")
        return ""
    for p in published:
        if p.get("youtube_id") in st:
            p["views"], p["likes"] = st[p["youtube_id"]]["views"], st[p["youtube_id"]]["likes"]
    rows = sorted((p for p in published if p.get("views") is not None), key=lambda p: -p["views"])
    if not rows or rows[0]["views"] == 0:
        return ""
    return "; ".join(f'"{p["title"]}" = {p["views"]} views, {p.get("likes", 0)} likes' for p in rows[:8])


# ───────────────────────── render ─────────────────────────
def render(script_path, out_path):
    cmd = [sys.executable, str(HERE / "make_reel.py"), "render", str(script_path), "-o", str(out_path), "--work", str(OUT / "work")]
    if os.environ.get("IMAGE_API_KEY") or os.environ.get("IMAGE_PROVIDER"):
        cmd.append("--imagegen")
    cmd += os.environ.get("RENDER_ARGS", "").split()
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    print((r.stdout or "")[-2500:])
    if r.returncode:
        raise RuntimeError("render failed: " + ((r.stderr or "") + (r.stdout or ""))[-900:])


# ───────────────────────── main ─────────────────────────
def run(a):
    OUT.mkdir(exist_ok=True)
    topics, published = load(TOPICS, {"queue": []}), load(PUBLISHED, [])
    today = datetime.date.today().isoformat()
    voices = [v.strip() for v in os.environ.get("DAILY_VOICES", "am_onyx,bm_george").split(",") if v.strip()]
    narrator = voices[datetime.date.today().toordinal() % len(voices)]
    spec = None
    sources, issues = [], []
    perf = refresh_stats(published)
    if perf:
        print("› learning from past results:", perf[:200])
    if a.script:                                   # test path: use an existing script and skip the AI steps
        spec = sanitize(json.load(open(a.script, encoding="utf-8")), narrator)
        topic = {"topic": spec.get("title", "test")}
    else:
        for attempt in range(5):
            topic = {"topic": a.topic, "hint": ""} if a.topic else pick_topic(topics, published)
            if topic is None:
                print("› topic queue empty — asking Claude for new legends")
                topics = refill_topics(topics, published)
                save(TOPICS, topics)
                topic = pick_topic(topics, published)
            print(f"› topic: {topic['topic']}")
            try:
                sources_text, sources = gather_sources(topic["topic"])
                if not sources_text.strip():
                    raise Rejected("no reliable source text found for this topic")
                spec = generate_script(topic, a.scenes, narrator, sources_text, perf)
                spec, issues = factcheck(spec, narrator, sources_text)
                break
            except Rejected as e:
                print("  rejected:", e)
                for t in topics["queue"]:
                    if t["topic"] == topic["topic"]:
                        t["status"] = "rejected"
                save(TOPICS, topics)
                if a.topic:
                    raise
        if spec is None:
            raise RuntimeError("could not produce an accepted script after 5 topics")
        print(f"  fact-check issues fixed/noted: {len(issues)}")
    title, desc, tags, tiktok_caption = build_meta(spec, topic, sources)
    slug = re.sub(r"[^a-z0-9]+", "-", topic["topic"].lower()).strip("-")[:40] or "legend"
    script_path, video_path = OUT / f"{today}-{slug}.json", OUT / f"{today}-{slug}.mp4"
    save(script_path, spec)
    print("› rendering…")
    render(script_path, video_path)
    record = {"date": today, "topic": topic["topic"], "title": title, "file": video_path.name, "youtube_id": None}
    if a.dry_run:
        print("✔ dry run finished:", video_path)
        return
    yt_id = None
    if not a.no_youtube:
        privacy = os.environ.get("YT_PRIVACY", "private")
        print(f"› uploading to YouTube ({privacy})…")
        yt_id = pub.youtube_upload(video_path, title, desc, tags, privacy=privacy,
                                   ai_disclosure=os.environ.get("YT_AI_DISCLOSURE", "true").lower() != "false")
        record["youtube_id"] = yt_id
        print("  https://youtu.be/" + yt_id)
    if not a.no_telegram:
        note = f"TikTok caption:\n{tiktok_caption}\n"
        if yt_id:
            note += f"\nYouTube: https://youtu.be/{yt_id} ({os.environ.get('YT_PRIVACY', 'private')})"
        try:
            pub.telegram_send_video(video_path, note)
        except pub.PublishError as e:
            print("  telegram:", e)
    published.append(record)
    save(PUBLISHED, published)
    save(TOPICS, topics)
    print("✔ done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="generate and render, but do not upload or send")
    ap.add_argument("--topic", help="force a specific legend instead of the queue")
    ap.add_argument("--scenes", type=int, default=11)
    ap.add_argument("--script", help="use an existing script JSON (skips the AI steps; for tests)")
    ap.add_argument("--no-youtube", action="store_true")
    ap.add_argument("--no-telegram", action="store_true")
    a = ap.parse_args()
    try:
        run(a)
    except Exception as e:                       # tell the owner, show the reason in the GitHub run page, then fail the job
        msg = f"{type(e).__name__}: {e}"
        print("::error title=Pipeline failed::" + msg.replace("\r", " ").replace("\n", " | ")[:1200])
        pub.telegram_message(f"❌ Daily legend pipeline failed: {msg[:500]}")
        raise


if __name__ == "__main__":
    main()
