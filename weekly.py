#!/usr/bin/env python3
"""
Weekly review - the 'learn what spreads' loop.

  1. reads views / likes / comments of every published video from YouTube,
  2. asks the AI what is working (with caution: few videos = weak evidence),
  3. writes playbook.json (guidance for the writer + weights for voice / hook style / length), which daily.py uses all week,
  4. moves the topics that match the winners to the front of topics.json and adds fresh ideas,
  5. sends the owner a short report in Arabic on Telegram.
"""
import datetime, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daily            # noqa: E402
import publishers as pub  # noqa: E402

MIN_AGE_DAYS, MIN_VIDEOS = 2, 6
HOOKS, LENGTHS_K = list(daily.HOOK_STYLES), list(daily.LENGTHS)

ANALYST = """You are the growth analyst of a faceless YouTube Shorts channel about folklore and urban legends (channel: Legends After Dark, English narration).
Below is the data of our recent videos (JSON). Fields: age_days, views, likes, comments, views_per_day, and the choices that varied between videos:
voice (narrator), hook_style, length (short/medium/long), topic, title, hook (first narration line), duration_s, arts.

Find what is working. Be CAUTIOUS: with few videos the evidence is weak; call something a pattern only if the difference is clear and repeated, otherwise say so.
Keep exploring: every option keeps a weight of at least 0.15 (voices at least 0.2).

Return ONLY JSON with exactly these keys:
{{
 "summary_ar": "5-8 short, simple Arabic sentences for a non-technical owner: what worked, what did not, what changes next week, and how sure you are",
 "guidance": "max 120 words of English instructions for the script writer for next week (hook patterns, tone, structure, topics), based on evidence only",
 "voice_weights": {{ {voices} }},
 "hook_weights": {{ {hooks} }},
 "length_weights": {{ {lengths} }},
 "topic_priorities": ["short keywords of topic types to do more of, e.g. 'snow yokai', 'school legends'"],
 "new_topics": [{{"topic": "...", "hint": "one sentence about what is well documented"}}],
 "visual_ideas_ar": ["up to 3 short Arabic suggestions for improving visuals or editing that the owner could ask Claude to build"]
}}
All weights are numbers between 0 and 1 and each group sums to 1. new_topics: up to 6, well-documented, no gore, no real tragedies, not already covered.
Videos already covered: {covered}

DATA:
{data}
"""


def age_days(rec):
    t = rec.get("published_at")
    try:
        dt = datetime.datetime.fromisoformat(t) if t else datetime.datetime.fromisoformat(rec["date"]).replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return 0.0
    return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 86400


def normalize(weights, keys, floor):
    w = {k: max(floor, float((weights or {}).get(k, 1.0 / len(keys)))) for k in keys}
    s = sum(w.values())
    return {k: round(v / s, 3) for k, v in w.items()}


def reorder(topics, published, res):
    have = {t["topic"].lower() for t in topics["queue"]} | {p["topic"].lower() for p in published}
    new = [{"topic": str(n["topic"]), "hint": str(n.get("hint", ""))} for n in (res.get("new_topics") or [])[:6]
           if isinstance(n, dict) and n.get("topic") and str(n["topic"]).lower() not in have]
    prio = [str(k).lower() for k in (res.get("topic_priorities") or []) if k]

    def score(t):
        text = (t["topic"] + " " + t.get("hint", "")).lower()
        return -sum(1 for k in prio if any(w in text for w in k.split() if len(w) > 3))

    topics["queue"] = sorted(new + topics["queue"], key=score)       # stable: ties keep their order
    return topics, len(new)


def main():
    published = daily.load(daily.PUBLISHED, [])
    daily.refresh_stats(published)
    rows = []
    for p in published:
        if p.get("youtube_id") and p.get("views") is not None:
            age = age_days(p)
            rows.append({"age_days": round(age, 1), "views": p["views"], "likes": p.get("likes", 0), "comments": p.get("comments", 0),
                         "views_per_day": round(p["views"] / max(age, 1.0), 1), "voice": p.get("voice"), "hook_style": p.get("hook_style"),
                         "length": p.get("length"), "topic": p["topic"], "title": p["title"], "hook": p.get("hook"),
                         "duration_s": p.get("duration_s"), "arts": sorted(set(p.get("arts") or []))})
    daily.save(daily.PUBLISHED, published)
    mature = [r for r in rows if r["age_days"] >= MIN_AGE_DAYS]
    if len(mature) < MIN_VIDEOS:
        msg = (f"📈 تقرير الأسبوع\nعدد الفيديوهات المنشورة: {len(rows)}. لا توجد بيانات كافية للحكم بعد "
               f"(أحتاج {MIN_VIDEOS} فيديوهات عمرها {MIN_AGE_DAYS} أيام على الأقل). أستمر في تجربة أنماط مختلفة وأحلّل في الأسبوع القادم.")
        pub.telegram_message(msg)
        print(msg)
        return
    old = daily.load(daily.PLAYBOOK, {})
    voices = sorted({r["voice"] for r in mature if r.get("voice")}) or ["am_onyx", "bm_george"]
    prompt = ANALYST.format(voices=", ".join(f'"{v}": 0.5' for v in voices), hooks=", ".join(f'"{h}": 0.25' for h in HOOKS),
                            lengths=", ".join(f'"{k}": 0.33' for k in LENGTHS_K), covered=[p["topic"] for p in published][-40:],
                            data=json.dumps(sorted(rows, key=lambda r: -r["views_per_day"])[:60], ensure_ascii=False))
    res = daily.extract_json(daily.llm(prompt))
    pb = {"updated": datetime.date.today().isoformat(), "based_on_videos": len(mature),
          "guidance": str(res.get("guidance", ""))[:1200],
          "voice_weights": normalize(res.get("voice_weights"), voices, 0.2),
          "hook_weights": normalize(res.get("hook_weights"), HOOKS, 0.15),
          "length_weights": normalize(res.get("length_weights"), LENGTHS_K, 0.15),
          "topic_priorities": [str(k) for k in (res.get("topic_priorities") or [])][:8], "previous": {k: old.get(k) for k in ("guidance", "voice_weights", "hook_weights", "length_weights")}}
    daily.save(daily.PLAYBOOK, pb)
    topics, added = reorder(daily.load(daily.TOPICS, {"queue": []}), published, res)
    daily.save(daily.TOPICS, topics)
    msg = "📈 تقرير الأسبوع\n" + str(res.get("summary_ar", "")).strip()
    ideas = [str(i) for i in (res.get("visual_ideas_ar") or [])][:3]
    if ideas:
        msg += "\n\nأفكار لتحسين الشكل (يمكنك أن تطلبها من Claude):\n- " + "\n- ".join(ideas)
    msg += f"\n\nأضفت {added} مواضيع جديدة وأعدت ترتيب القائمة."
    pub.telegram_message(msg)
    print("✔ playbook updated:", json.dumps({k: pb[k] for k in ("voice_weights", "hook_weights", "length_weights")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        pub.telegram_message(f"❌ فشل التقرير الأسبوعي: {type(e).__name__}: {str(e)[:300]}")
        print("::error title=Weekly review failed::" + f"{type(e).__name__}: {e}".replace("\n", " | ")[:1000])
        raise
