#!/usr/bin/env python3
"""
Stickman Reels Maker v4 — faceless YouTube Shorts generator.

  python make_reel.py gen "why is the sky blue" --lang en -o script.json   # script via Claude API (optional)
  python make_reel.py render script.json -o reel.mp4                       # voice + animation + captions + music

Needs: ffmpeg, pillow, numpy, edge-tts (+ arabic-reshaper, python-bidi only if Pillow lacks raqm)
"""
import argparse, asyncio, base64, hashlib, importlib.util, json, math, multiprocessing as mp, os, random, re, shutil, subprocess, sys, tempfile, time, urllib.request, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None

W, H, FPS, SS, SR = 1080, 1920, 30, 2, 44100
HERE = Path(__file__).resolve().parent
GH = "https://github.com/google/fonts/raw/main/ofl/"
FONTS = {"anton": ("Anton-Regular.ttf", GH + "anton/Anton-Regular.ttf"),
         "bangers": ("Bangers-Regular.ttf", GH + "bangers/Bangers-Regular.ttf"),
         "tajawal": ("Tajawal-ExtraBold.ttf", GH + "tajawal/Tajawal-ExtraBold.ttf")}

VOICES = {"ar": "ar-SA-HamedNeural", "en": "en-US-GuyNeural", "fr": "fr-FR-HenriNeural", "es": "es-ES-AlvaroNeural"}
KOKORO_VOICES = {"en": "af_heart", "fr": "ff_siwis", "es": "em_alex"}
KOKORO_LANG = {"en": "en-us", "fr": "fr-fr", "es": "es"}
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
EL_DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
POSES = ["idle", "talk", "wave", "walk", "run", "think", "point", "celebrate", "sad", "shock", "dance", "angry", "scared", "laugh"]
PROPS = ["question", "exclam", "bulb", "coin", "money", "heart", "star", "check", "cross", "arrow", "clock", "fire", "moon", "earth", "sun"]
ENVS = ["sky", "city", "room", "night", "night0", "ocean", "moon", "plain"]
ENV_CYCLE = ["sky", "city", "room", "night", "plain"]   # night0 = night without the Moon
THEMES = {  # used by the "plain" environment
    "light": dict(ink="#111111", bgs=[("#FFF6E5", "#FFD9A0"), ("#E8F7FF", "#B7E3FF"), ("#FFEDEF", "#FFC2CB")]),
    "dark": dict(ink="#F5F5F5", bgs=[("#111827", "#1F2A44"), ("#1B1030", "#3A1C71")]),
}
ACCENT, GOLD = "#FF3D57", "#FFC400"
CAP_COLORS = ["#FFE600", "#39FF88", "#FF5CAA", "#4DD2FF"]
GY = 1320                                   # ground line
HAS_RAQM = features.check("raqm")           # Pillow shapes Arabic natively with raqm


# ───────────────────────── text / font helpers ─────────────────────────
_fonts = {}


def font_path(key, user=None):
    if user:
        return user
    name, url = FONTS[key]
    p = HERE / "fonts" / name
    if not p.exists():
        (HERE / "fonts").mkdir(exist_ok=True)
        print("Downloading font", name)
        urllib.request.urlretrieve(url, p)
    return str(p)


def font(path, size):
    k = (path, int(size))
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, int(size))
    return _fonts[k]


def has_ar(s):
    return bool(re.search(r"[\u0600-\u06FF]", s))


def shape(s):
    if HAS_RAQM:
        return s
    if arabic_reshaper and has_ar(s):
        return get_display(arabic_reshaper.reshape(s))
    return s


def wrap_lines(text, f, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(shape(t)) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend(a, b, t):
    a = hex2rgb(a) if isinstance(a, str) else a
    b = hex2rgb(b) if isinstance(b, str) else b
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def ease_back(x):
    x = max(0.0, min(1.0, x))
    return 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2


# ───────────────────────── stickman ─────────────────────────
LWD = 19
HR, TORSO, UA, FA, TH, SH = 80, 250, 135, 135, 150, 150
HIP = (540, GY - TH - SH - 10)
LX0, LY0, LW_, LH_ = 90, 330, 900, 1030     # figure layer (global coords)


def P(x, y):
    return ((x - LX0) * SS, (y - LY0) * SS)


def pose(name, t):
    s = math.sin
    p = dict(lean=0, bob=0, head=0, la=(-22, -8), ra=(22, 8), ll=(-7, 0), rl=(7, 0), face="smile", jump=0)
    if name in ("idle", "talk"):
        p["bob"] = 5 * s(t * 5)
        if name == "talk":
            p["ra"] = (38 + 22 * s(t * 3.3), 25 * s(t * 4.1))
            p["la"] = (-30 - 12 * s(t * 2.7), -15 * s(t * 3.7))
            p["head"] = 4 * s(t * 2)
    elif name == "wave":
        p["ra"] = (160, 28 * s(t * 11))
        p["bob"] = 4 * s(t * 5)
    elif name in ("walk", "run"):
        k = 1 if name == "walk" else 1.6
        ph = t * 7 * k
        ll_, rl_ = max(0, s(ph)), max(0, -s(ph))          # which knee is lifted (front view: knee goes outward)
        p["ll"] = (-6 - 30 * k ** 0.5 * ll_, 55 * k ** 0.5 * ll_)
        p["rl"] = (6 + 30 * k ** 0.5 * rl_, -55 * k ** 0.5 * rl_)
        p["la"] = (-22 + 16 * s(ph), -20 * k)
        p["ra"] = (22 + 16 * s(ph), 20 * k)
        p["bob"] = -9 * abs(s(ph)) + 5
        p["lean"] = 0 if name == "walk" else 7
    elif name == "think":
        p.update(ra=(50, 151), head=9, face="think", bob=4 * s(t * 3))
    elif name == "point":
        p.update(ra=(95 + 6 * s(t * 6), 0), la=(-14, -6), lean=4)
    elif name == "celebrate":
        p.update(jump=60 * abs(s(t * 2 * math.pi * 1.4)), la=(-150 + 8 * s(t * 9), 10),
                 ra=(150 - 8 * s(t * 9), -10), ll=(-16, 12), rl=(16, -12), face="big")
    elif name == "sad":
        p.update(lean=6, head=14, la=(-6, 0), ra=(6, 0), face="sad", bob=3 * s(t * 2))
    elif name == "shock":
        k = min(1, t / 0.18)
        p.update(jump=75 * s(min(t, 0.45) / 0.45 * math.pi), la=(-120 * k, 30), ra=(120 * k, -30),
                 ll=(-14, 0), rl=(14, 0), lean=-4, face="surprised")
    elif name == "dance":
        ph = t * 9
        p.update(jump=24 * abs(s(ph)), la=(-100 + 70 * s(ph), 25), ra=(100 + 70 * s(ph + math.pi), -25),
                 ll=(-10 + 12 * s(ph), 0), rl=(10 + 12 * s(ph), 0), lean=7 * s(ph / 2), face="big")
    elif name == "angry":
        p.update(la=(-35, -90), ra=(35, 90), face="angry", bob=3 * s(t * 18))
    elif name == "scared":
        tr = 3 * s(t * 38)
        p.update(la=(-55 + tr, -149), ra=(55 - tr, 149), ll=(-9, 0), rl=(9, 0), lean=-3,
                 bob=2 * s(t * 30), head=3 * s(t * 25), face="scared")
    elif name == "laugh":
        p.update(bob=-14 * abs(s(t * 13)), head=-9 + 3 * s(t * 13), la=(-32, -40), ra=(32, 40), face="laugh", lean=-4)
    return p


def limb(p0, a, b, l1, l2):
    r = math.radians
    x1, y1 = p0[0] + l1 * math.sin(r(a)), p0[1] + l1 * math.cos(r(a))
    return (x1, y1), (x1 + l2 * math.sin(r(a + b)), y1 + l2 * math.cos(r(a + b)))


def seg(d, pts, ink):
    q = [P(*p) for p in pts]
    w = LWD * SS
    d.line(q, fill=ink, width=w, joint="curve")
    for x, y in q:
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ink)


def draw_face(d, hc, ang, face, amp, t, ink, c):
    cx, cy = hc
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def R(dx, dy):
        return P(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

    glasses = c.get("glasses")
    blink = (t % 3.1) > 2.98 and face not in ("laugh", "scared", "surprised")
    for sx in (-1, 1):
        ex, ey = R(sx * 28, -10)
        if face == "laugh":
            d.arc([ex - 13 * SS, ey - 8 * SS, ex + 13 * SS, ey + 14 * SS], 200, 340, fill=ink, width=5 * SS)
        elif face in ("surprised", "scared"):
            rr = (13 if face == "surprised" else 16) * SS
            d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill="#FFFFFF", outline=ink, width=4 * SS)
            jx = 3 * SS * math.sin(t * 40) if face == "scared" else 0
            pr = (4 if face == "surprised" else 3) * SS
            d.ellipse([ex + jx - pr, ey - pr, ex + jx + pr, ey + pr], fill="#000000")
        elif blink:
            d.line([ex - 9 * SS, ey, ex + 9 * SS, ey], fill=ink, width=4 * SS)
        else:
            rr = 8 * SS
            d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=ink)
        if glasses:
            gr = 24 * SS
            d.ellipse([ex - gr, ey - gr, ex + gr, ey + gr], outline=ink, width=4 * SS)
    if glasses:
        d.line([R(-5, -10), R(5, -10)], fill=ink, width=4 * SS)
    for sx in (-1, 1):
        if face == "angry":
            d.line([R(sx * 48, -40), R(sx * 12, -24)], fill=ink, width=6 * SS)
        elif face in ("sad", "scared"):
            d.line([R(sx * 46, -30), R(sx * 12, -46)], fill=ink, width=5 * SS)
        elif face == "surprised":
            d.line([R(sx * 44, -48), R(sx * 14, -48)], fill=ink, width=5 * SS)
    if face == "blush":
        for sx in (-1, 1):
            bx, by = R(sx * 46, 14)
            d.ellipse([bx - 13 * SS, by - 8 * SS, bx + 13 * SS, by + 8 * SS], fill="#FF8FA3")
    mx, my = R(0, 28)
    op = amp > 0.12
    if face == "surprised":
        h = (14 + 16 * amp) * SS
        d.ellipse([mx - 11 * SS, my - 4 * SS, mx + 11 * SS, my - 4 * SS + h], outline=ink, width=4 * SS)
    elif face == "laugh":
        d.pieslice([mx - 30 * SS, my - 26 * SS, mx + 30 * SS, my + 24 * SS], 0, 180, fill=ink)
    elif op:
        h = (8 + 30 * amp) * SS
        d.ellipse([mx - 17 * SS, my - h / 2, mx + 17 * SS, my + h / 2], fill=ink)
    elif face == "scared":
        d.line([R(-24 + i * 8, 30 + (6 if i % 2 else -2)) for i in range(7)], fill=ink, width=5 * SS, joint="curve")
    elif face == "big":
        d.pieslice([mx - 26 * SS, my - 24 * SS, mx + 26 * SS, my + 20 * SS], 0, 180, fill=ink)
    elif face in ("smile", "blush"):
        d.arc([mx - 24 * SS, my - 26 * SS, mx + 24 * SS, my + 10 * SS], 20, 160, fill=ink, width=5 * SS)
    elif face in ("sad", "angry"):
        d.arc([mx - 22 * SS, my - 2 * SS, mx + 22 * SS, my + 28 * SS], 200, 340, fill=ink, width=5 * SS)
    elif face == "think":
        d.line([mx - 15 * SS, my, mx + 15 * SS, my - 5 * SS], fill=ink, width=5 * SS)
    if face == "scared":   # sweat drop
        sx_, sy_ = R(64, -50)
        d.polygon([(sx_, sy_ - 18 * SS), (sx_ - 10 * SS, sy_ + 2 * SS), (sx_ + 10 * SS, sy_ + 2 * SS)], fill="#4DB8FF")
        d.ellipse([sx_ - 10 * SS, sy_ - 6 * SS, sx_ + 10 * SS, sy_ + 14 * SS], fill="#4DB8FF")
    return R


def draw_prop(d, name, X, Y, t, ink, f):
    Y += 12 * math.sin(t * 6) * SS
    if name in ("question", "exclam"):
        d.text((X, Y), "?" if name == "question" else "!", font=f, fill=ACCENT, anchor="mm",
               stroke_width=4 * SS, stroke_fill="#000000")
    elif name == "bulb":
        r = 56 * SS
        d.ellipse([X - r, Y - r, X + r, Y + r], fill=GOLD, outline="#000000", width=5 * SS)
        d.rectangle([X - 24 * SS, Y + r - 4 * SS, X + 24 * SS, Y + r + 28 * SS], fill="#333333")
        if math.sin(t * 9) > -0.3:
            for k in range(8):
                a = k * math.pi / 4
                d.line([X + math.cos(a) * (r + 16 * SS), Y + math.sin(a) * (r + 16 * SS),
                        X + math.cos(a) * (r + 44 * SS), Y + math.sin(a) * (r + 44 * SS)], fill=GOLD, width=7 * SS)
    elif name == "coin":
        r = 62 * SS
        d.ellipse([X - r, Y - r, X + r, Y + r], fill=GOLD, outline="#000000", width=5 * SS)
        d.text((X, Y), "$", font=f, fill="#000000", anchor="mm")
    elif name == "money":
        w, h = 120 * SS, 70 * SS
        d.rounded_rectangle([X - w, Y - h, X + w, Y + h], 12 * SS, fill="#3DDC84", outline="#000000", width=5 * SS)
        d.ellipse([X - 40 * SS, Y - 40 * SS, X + 40 * SS, Y + 40 * SS], outline="#000000", width=5 * SS)
    elif name == "heart":
        sc = (5.6 + 0.6 * math.sin(t * 8)) * SS
        pts = []
        for i in range(60):
            a = i / 60 * 2 * math.pi
            hx = 16 * math.sin(a) ** 3
            hy = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
            pts.append((X + hx * sc, Y - hy * sc))
        d.polygon(pts, fill=ACCENT, outline="#000000")
    elif name == "star":
        sc = (1 + 0.12 * math.sin(t * 7)) * 68 * SS
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = sc if i % 2 == 0 else sc * 0.45
            pts.append((X + rr * math.cos(a), Y + rr * math.sin(a)))
        d.polygon(pts, fill=GOLD, outline="#000000")
    elif name == "check":
        d.line([X - 60 * SS, Y, X - 16 * SS, Y + 50 * SS, X + 66 * SS, Y - 56 * SS], fill="#22C55E", width=22 * SS, joint="curve")
    elif name == "cross":
        d.line([X - 55 * SS, Y - 55 * SS, X + 55 * SS, Y + 55 * SS], fill=ACCENT, width=22 * SS)
        d.line([X - 55 * SS, Y + 55 * SS, X + 55 * SS, Y - 55 * SS], fill=ACCENT, width=22 * SS)
    elif name == "arrow":
        d.polygon([(X - 32 * SS, Y - 64 * SS), (X + 32 * SS, Y - 64 * SS), (X + 32 * SS, Y), (X + 64 * SS, Y),
                   (X, Y + 64 * SS), (X - 64 * SS, Y), (X - 32 * SS, Y)], fill=ACCENT, outline="#000000")
    elif name == "clock":
        r = 62 * SS
        d.ellipse([X - r, Y - r, X + r, Y + r], fill="#FFFFFF", outline="#000000", width=6 * SS)
        a = t * 4
        d.line([X, Y, X + math.sin(a) * 46 * SS, Y - math.cos(a) * 46 * SS], fill="#000000", width=6 * SS)
        d.line([X, Y, X + math.sin(a / 12) * 30 * SS, Y - math.cos(a / 12) * 30 * SS], fill="#000000", width=7 * SS)
    elif name == "fire":
        k = 1 + 0.08 * math.sin(t * 14)
        pts = [(0, -90), (30, -40), (55, -10), (50, 40), (20, 70), (-20, 70), (-50, 40), (-55, -10), (-30, -45), (-18, -70)]
        d.polygon([(X + px * SS * k, Y + py * SS * k) for px, py in pts], fill="#FF7A00", outline="#000000")
        pts2 = [(0, -30), (22, 5), (18, 50), (-18, 50), (-22, 5)]
        d.polygon([(X + px * SS * k, Y + 15 * SS + py * SS * k) for px, py in pts2], fill=GOLD)
    elif name == "moon":
        r = 66 * SS
        d.ellipse([X - r, Y - r, X + r, Y + r], fill="#F4F1DE", outline="#000000", width=5 * SS)
        for cx_, cy_, cr in ((-22, -18, 14), (20, 8, 18), (-8, 30, 10)):
            d.ellipse([X + (cx_ - cr) * SS, Y + (cy_ - cr) * SS, X + (cx_ + cr) * SS, Y + (cy_ + cr) * SS], fill="#D5D0B4")
    elif name == "sun":
        r = 58 * SS
        for k in range(12):
            a = k * math.pi / 6 + t
            d.line([X + math.cos(a) * (r + 10 * SS), Y + math.sin(a) * (r + 10 * SS),
                    X + math.cos(a) * (r + 40 * SS), Y + math.sin(a) * (r + 40 * SS)], fill=GOLD, width=8 * SS)
        d.ellipse([X - r, Y - r, X + r, Y + r], fill=GOLD, outline="#000000", width=5 * SS)
    elif name == "earth":
        r = 68 * SS
        d.ellipse([X - r, Y - r, X + r, Y + r], fill="#2F80ED", outline="#000000", width=5 * SS)
        for pts in (((-40, -30), (-10, -48), (6, -20), (-20, -2), (-44, -10)), ((10, 8), (40, 0), (48, 30), (22, 46), (6, 28))):
            d.polygon([(X + px * SS, Y + py * SS) for px, py in pts], fill="#3DBE5A")
        a = math.radians(24 + 26 * math.sin(t * 3.2))
        d.line([X - math.sin(a) * 100 * SS, Y - math.cos(a) * 100 * SS, X + math.sin(a) * 100 * SS, Y + math.cos(a) * 100 * SS],
               fill="#FFFFFF", width=6 * SS)


PL = 520   # prop layer size


def prop_layer(name, t, ink, f):
    lay = Image.new("RGBA", (PL * SS, PL * SS), (0, 0, 0, 0))
    draw_prop(ImageDraw.Draw(lay), name, PL * SS / 2, PL * SS / 2, t, ink, f)
    return lay


def thick(d, pts, color, w, ow=5, outline="#000000"):
    """Thick limb/garment stroke with a black outline and round ends."""
    q = [P(*p) for p in pts]
    if outline:
        wo = (w + 2 * ow) * SS
        d.line(q, fill=outline, width=int(wo), joint="curve")
        for x, y in (q[0], q[-1]):
            d.ellipse([x - wo / 2, y - wo / 2, x + wo / 2, y + wo / 2], fill=outline)
    wc = w * SS
    d.line(q, fill=color, width=int(wc), joint="curve")
    for x, y in (q[0], q[-1]):
        d.ellipse([x - wc / 2, y - wc / 2, x + wc / 2, y + wc / 2], fill=color)


_SHADOW = [0.6, 0.8]      # direction the shadow side faces (set per character; mirrored for flipped ones)


def chaikin(pts, n=2, closed=True):
    """Round off a polygon's corners (gives clothes an organic outline instead of sharp rectangles)."""
    for _ in range(n):
        out, m = [], len(pts)
        for i in range(m if closed else m - 1):
            a, b = pts[i], pts[(i + 1) % m]
            out += [(0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]), (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])]
        pts = out
    return pts


def _quad(p0, p1, w0, w1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    return [(p0[0] + nx * w0 / 2, p0[1] + ny * w0 / 2), (p1[0] + nx * w1 / 2, p1[1] + ny * w1 / 2),
            (p1[0] - nx * w1 / 2, p1[1] - ny * w1 / 2), (p0[0] - nx * w0 / 2, p0[1] - ny * w0 / 2)], (nx, ny), (dx / L, dy / L)


def silhouette(pts, widths, sub=6, bulge=0.07):
    """Smooth organic outline for a sleeve / trouser leg: tapered, slightly bulging, round start cap."""
    C, Wd = [], []
    for i in range(len(pts) - 1):
        for k in range(sub):
            t = k / sub
            C.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t))
            Wd.append((widths[i] + (widths[i + 1] - widths[i]) * t) * (1 + bulge * math.sin(math.pi * t)))
    C.append(pts[-1])
    Wd.append(widths[-1])
    n, Lp, Rp, Nn = len(C), [], [], []
    for k in range(n):
        a, b = C[max(0, k - 1)], C[min(n - 1, k + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        Nn.append((nx, ny))
        Lp.append((C[k][0] + nx * Wd[k] / 2, C[k][1] + ny * Wd[k] / 2))
        Rp.append((C[k][0] - nx * Wd[k] / 2, C[k][1] - ny * Wd[k] / 2))
    a0 = math.atan2(C[1][1] - C[0][1], C[1][0] - C[0][0])
    cap = [(C[0][0] + Wd[0] / 2 * math.cos(a0 - math.pi / 2 - math.pi * j_ / 8),
            C[0][1] + Wd[0] / 2 * math.sin(a0 - math.pi / 2 - math.pi * j_ / 8)) for j_ in range(1, 8)]
    return Lp + Rp[::-1] + cap, C, Wd, Nn


def garment(d, pts, widths, color, cuff=None, cuff_len=12, bulge=0.07):
    poly, C, Wd, Nn = silhouette(pts, widths, bulge=bulge)
    sm = [P(*q) for q in chaikin(poly, 2)]
    d.polygon(sm, fill=color)
    # shading stripe along the shadow side
    sgn = 1 if (Nn[0][0] * _SHADOW[0] + Nn[0][1] * _SHADOW[1]) >= 0 else -1
    outer = [(C[k][0] + sgn * Nn[k][0] * Wd[k] * 0.46, C[k][1] + sgn * Nn[k][1] * Wd[k] * 0.46) for k in range(len(C))]
    inner = [(C[k][0] + sgn * Nn[k][0] * Wd[k] * 0.16, C[k][1] + sgn * Nn[k][1] * Wd[k] * 0.16) for k in range(len(C))]
    d.polygon([P(*q) for q in chaikin(outer + inner[::-1], 1)], fill=blend(color, "#000000", 0.20))
    if cuff:   # rounded cuff / hem band at the open end
        a, b = pts[-2], pts[-1]
        ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        ux, uy = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
        c0 = (b[0] - ux * cuff_len, b[1] - uy * cuff_len)
        wc = widths[-1] + 4
        nx, ny = -uy, ux
        band = [(c0[0] + nx * wc / 2, c0[1] + ny * wc / 2), (b[0] + nx * wc / 2, b[1] + ny * wc / 2),
                (b[0] - nx * wc / 2, b[1] - ny * wc / 2), (c0[0] - nx * wc / 2, c0[1] - ny * wc / 2)]
        bp = [P(*q) for q in chaikin(band, 2)]
        d.polygon(bp, fill=cuff)
        d.line(bp + [bp[0]], fill="#000000", width=3 * SS, joint="curve")
    d.line(sm + [sm[0]], fill="#000000", width=5 * SS, joint="curve")


def u_x(Q, i):
    a, b = Q[i], Q[i + 1]
    return (b[0] - a[0]) / (math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0)


def u_y(Q, i):
    a, b = Q[i], Q[i + 1]
    return (b[1] - a[1]) / (math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0)


def draw_hand(d, wrist, forearm_dir, fill):
    """Mitten hand with a thumb."""
    x, y = P(*wrist)
    dx, dy = forearm_dir
    nx, ny = -dy, dx
    tx, ty = x + (dx * 6 + nx * 15) * SS, y + (dy * 6 + ny * 15) * SS
    d.ellipse([tx - 8 * SS, ty - 8 * SS, tx + 8 * SS, ty + 8 * SS], fill=fill, outline="#000000", width=4 * SS)
    d.ellipse([x - 17 * SS, y - 17 * SS, x + 17 * SS, y + 17 * SS], fill=fill, outline="#000000", width=4 * SS)


def draw_shoe(d, foot, side, color):
    fx, fy = foot[0], foot[1] - 9
    s = side
    pts = [(fx - s * 16, fy - 20), (fx + s * 8, fy - 22), (fx + s * 28, fy - 8), (fx + s * 46, fy + 4), (fx + s * 46, fy + 14), (fx - s * 20, fy + 14)]
    q = [P(*p) for p in chaikin(pts, 2)]
    d.polygon(q, fill=color)
    d.line(q + [q[0]], fill="#000000", width=4 * SS, joint="curve")
    sole = [P(fx - s * 21, fy + 9), P(fx + s * 47, fy + 9), P(fx + s * 47, fy + 19), P(fx - s * 21, fy + 19)]
    d.polygon(sole, fill="#F5F5F5")
    d.line(sole + [sole[0]], fill="#000000", width=3 * SS, joint="curve")
    for k in range(3):   # laces
        lx, ly = P(fx + s * (4 + 11 * k), fy - 14 + 4 * k)
        d.line([lx - 5 * SS, ly, lx + 5 * SS, ly + 3 * SS], fill="#FFFFFF", width=3 * SS)


def render_char(c, pose_name, face_override, t, amp, ink, head_fill, face_ink, flip=False):
    """Draw one character on its own layer. Returns (layer, head_center_in_global_coords)."""
    p = pose(pose_name, t)
    if face_override:
        p["face"] = face_override
    _SHADOW[0], _SHADOW[1] = (-0.6, 0.8) if flip else (0.6, 0.8)   # layer is mirrored later when flip=True
    side_sh = -1 if flip else 1
    layer = Image.new("RGBA", (LW_ * SS, LH_ * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    hx, hy = HIP[0], HIP[1] + p["bob"] - p["jump"]
    lean = math.radians(p["lean"])
    neck = (hx + TORSO * math.sin(lean), hy - TORSO * math.cos(lean))
    shoulder = (hx + TORSO * 0.9 * math.sin(lean), hy - TORSO * 0.9 * math.cos(lean))
    ang = p["head"] + p["lean"]
    hc = (neck[0] + HR * math.sin(math.radians(ang)), neck[1] - HR * math.cos(math.radians(ang)))
    shirt, coat, pants = c.get("shirt"), c.get("coat"), c.get("pants")
    ux, uy = math.cos(lean), math.sin(lean)

    def tpt(u, off=0.0):          # point on the torso: u=0 hip … 1 shoulder, off = sideways offset
        return (hx + (shoulder[0] - hx) * u + ux * off, hy + (shoulder[1] - hy) * u + uy * off)

    # ── legs (trousers / shorts) and shoes ──
    for (a, b), side in ((p["ll"], -1), (p["rl"], 1)):
        start = (hx + side * (24 if pants else 6), hy)
        k, f = limb(start, a, b, TH, SH)
        if pants:
            if c.get("shorts"):
                seg(d, [k, f], ink)
                mid = (start[0] + (k[0] - start[0]) * 0.74, start[1] + (k[1] - start[1]) * 0.74)
                garment(d, [start, mid], [46, 52], pants, cuff=blend(pants, "#FFFFFF", 0.28), cuff_len=9, bulge=0.04)
            else:
                garment(d, [start, k, f], [44, 39, 32], pants, cuff=blend(pants, "#000000", 0.22), cuff_len=13, bulge=0.05)
        else:
            seg(d, [start, k, f], ink)
        if c.get("shoes"):
            draw_shoe(d, f, side, c["shoes"])
    # ── torso: shirt / lab coat (rounded outline, shading, collar) ──
    if shirt:
        hem = -0.30 if coat else 0.0
        wh = 58 if coat else 42
        pts = [tpt(hem, -wh), tpt(0.05, -(wh - 6)), tpt(0.40, -40), tpt(0.80, -50), tpt(1.0, -54), tpt(1.07, -26),
               tpt(1.07, 26), tpt(1.0, 54), tpt(0.80, 50), tpt(0.40, 40), tpt(0.05, wh - 6), tpt(hem, wh)]
        poly = [P(*q) for q in chaikin(pts, 2)]
        d.polygon(poly, fill=shirt)
        sh_col = blend(shirt, "#000000", 0.16)
        d.polygon([P(*q) for q in (tpt(hem, side_sh * (wh - 4)), tpt(0.40, side_sh * 37), tpt(1.0, side_sh * 50),
                                   tpt(1.0, side_sh * 22), tpt(0.40, side_sh * 17), tpt(hem, side_sh * 16))], fill=sh_col)
        if c.get("stripe") and not coat:
            band = [tpt(0.40, -45), tpt(0.40, 45), tpt(0.58, 47), tpt(0.58, -47)]
            d.polygon([P(*q) for q in band], fill=c["stripe"])
        d.line(poly + [poly[0]], fill="#000000", width=5 * SS, joint="curve")
        sx_, sy_ = P(*shoulder)
        if coat:   # lab coat: blue shirt in the V, white lapels, buttons, pocket, hem line
            inner = c.get("inner", "#5DA9E9")
            vee = [tpt(1.07, -24), tpt(1.07, 24), tpt(0.30, 0)]
            d.polygon([P(*q) for q in vee], fill=inner, outline="#000000")
            for sg in (-1, 1):
                lap = [tpt(1.08, sg * 22), tpt(0.93, sg * 47), tpt(0.62, sg * 26), tpt(0.30, sg * 1), tpt(0.62, sg * 5)]
                lp = [P(*q) for q in chaikin(lap, 1)]
                d.polygon(lp, fill=shirt)
                d.line(lp + [lp[0]], fill="#000000", width=4 * SS, joint="curve")
            d.line([P(*tpt(0.30, 0)), P(*tpt(hem, 0))], fill="#000000", width=4 * SS)
            for u in (0.18, 0.06, -0.06):
                bx, by = P(*tpt(u, -9))
                d.ellipse([bx - 5 * SS, by - 5 * SS, bx + 5 * SS, by + 5 * SS], fill="#000000")
            pk = [tpt(0.10, 22), tpt(0.10, 46), tpt(0.30, 46), tpt(0.30, 22)]
            pkp = [P(*q) for q in chaikin(pk, 1)]
            d.line(pkp + [pkp[0]], fill="#000000", width=3 * SS, joint="curve")
            d.line([P(*tpt(0.30, 24)), P(*tpt(0.30, 44))], fill="#000000", width=3 * SS)
        else:      # t-shirt: scoop neckline
            d.pieslice([sx_ - 26 * SS, sy_ - 16 * SS, sx_ + 26 * SS, sy_ + 18 * SS], 0, 180, fill=head_fill, outline="#000000", width=4 * SS)
        seg(d, [shoulder, neck], ink)
    else:
        seg(d, [(hx, hy), neck], ink)
    sx_, sy_ = P(*shoulder)
    if c.get("tie"):
        d.polygon([(sx_ - 15 * SS, sy_ + 4 * SS), (sx_ + 15 * SS, sy_ + 4 * SS), (sx_ + 11 * SS, sy_ + 90 * SS),
                   (sx_, sy_ + 110 * SS), (sx_ - 11 * SS, sy_ + 90 * SS)], fill=ACCENT, outline="#000000")
    if c.get("bowtie"):
        for sg in (-1, 1):
            d.polygon([(sx_, sy_ + 14 * SS), (sx_ + sg * 34 * SS, sy_ - 2 * SS), (sx_ + sg * 34 * SS, sy_ + 30 * SS)],
                      fill=ACCENT, outline="#000000")
        d.ellipse([sx_ - 8 * SS, sy_ + 6 * SS, sx_ + 8 * SS, sy_ + 22 * SS], fill="#B3162E", outline="#000000")
    # ── arms: tapered sleeves + mitten hands ──
    long_sleeves = c.get("long_sleeves", bool(coat))
    sleeve = c.get("sleeve_color", shirt)
    for (a, b), side in ((p["la"], -1), (p["ra"], 1)):
        sh_pt = (shoulder[0] + side * ux * 46, shoulder[1] + side * uy * 46) if shirt else shoulder
        e, h = limb(sh_pt, a, b, UA, FA)
        if shirt:
            if long_sleeves:
                h2 = (e[0] + (h[0] - e[0]) * 0.90, e[1] + (h[1] - e[1]) * 0.90)
                garment(d, [sh_pt, e, h2], [44, 40, 35], sleeve, cuff=blend(sleeve, "#000000", 0.14), cuff_len=12)
            else:
                end = (sh_pt[0] + (e[0] - sh_pt[0]) * 0.62, sh_pt[1] + (e[1] - sh_pt[1]) * 0.62)
                seg(d, [end, e, h], ink)
                garment(d, [sh_pt, end], [46, 52], sleeve, cuff=blend(sleeve, "#FFFFFF", 0.30), cuff_len=10, bulge=0.04)
            fl = math.hypot(h[0] - e[0], h[1] - e[1]) or 1.0
            draw_hand(d, h, ((h[0] - e[0]) / fl, (h[1] - e[1]) / fl), head_fill)
        else:
            seg(d, [sh_pt, e, h], ink)
    cx, cy = P(*hc)
    r = HR * SS
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def R(dx, dy):
        return P(hc[0] + dx * ca - dy * sa, hc[1] + dx * sa + dy * ca)

    hair, hcol = c.get("hair"), c.get("hair_color", "#3B2A20")
    if hair == "spiky":
        for a_ in (-62, -31, 0, 31, 62):
            def pt(rad, deg):
                return R(rad * math.sin(math.radians(deg)), -rad * math.cos(math.radians(deg)))
            d.polygon([pt(HR * 0.9, a_ - 14), pt(HR * 1.5, a_), pt(HR * 0.9, a_ + 14)], fill=hcol, outline="#000000")
    elif hair == "bun":
        bx, by = R(0, -HR - 18)
        d.ellipse([bx - 30 * SS, by - 30 * SS, bx + 30 * SS, by + 30 * SS], fill=hcol, outline="#000000", width=4 * SS)
    elif hair == "ponytail":
        d.line([R(-HR * 0.8, -30), R(-HR * 1.5, 10), R(-HR * 1.3, 75)], fill=hcol, width=24 * SS, joint="curve")
    elif hair == "tufts":
        for sg in (-1, 1):
            for oy in (-30, 14):
                tx, ty = R(sg * (HR + 4), oy)
                d.ellipse([tx - 26 * SS, ty - 22 * SS, tx + 26 * SS, ty + 22 * SS], fill=hcol, outline="#000000", width=3 * SS)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=head_fill, outline=ink, width=LWD * SS)
    draw_face(d, hc, ang, p["face"], amp, t, face_ink, c)
    if c.get("mustache"):
        for sg in (-1, 1):
            mx_, my_ = R(sg * 15, 10)
            d.ellipse([mx_ - 17 * SS, my_ - 7 * SS, mx_ + 17 * SS, my_ + 7 * SS], fill=face_ink)
    if c.get("hat"):
        rr = r * 1.04
        hc_col = c.get("hat_color", ACCENT)
        d.chord([cx - rr, cy - rr, cx + rr, cy + rr], 200, 340, fill=hc_col, outline="#000000", width=5 * SS)
        d.polygon([R(4, -30), R(118, -24), R(118, -10), R(4, -17)], fill=hc_col, outline="#000000")
    return layer, hc



# ───────────────────────── environments ─────────────────────────
def make_gradient(top, bottom):
    mask = Image.linear_gradient("L").resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), hex2rgb(bottom)), Image.new("RGB", (W, H), hex2rgb(top)), mask)


def make_env(env, si, theme):
    rnd = random.Random(si * 131 + 7)
    if env == "sky":
        img = make_gradient("#59B8FF", "#D9F2FF")
        d = ImageDraw.Draw(img)
        d.ellipse([760, 220, 960, 420], fill="#FFE066")
        d.ellipse([-250, 1130, 750, 1560], fill="#8EDC8E")
        d.ellipse([350, 1170, 1450, 1600], fill="#74CC7A")
        d.rectangle([0, GY, W, H], fill="#52B35E")
        d.rectangle([0, GY, W, GY + 10], fill="#3E9A4A")
        return dict(bg=img, ink="#111111", head="#FFFFFF", env=env)
    if env == "city":
        img = make_gradient("#5D6DFF", "#FFB88C")
        d = ImageDraw.Draw(img)
        for layer, col, hmin, hmax in ((0, "#8A8FE0", 300, 700), (1, "#40449A", 250, 560)):
            x = -40 if layer == 0 else -90
            while x < W:
                bw = rnd.randint(110, 190)
                bh = rnd.randint(hmin, hmax)
                d.rectangle([x, GY - bh, x + bw, GY], fill=col)
                if layer == 1:
                    for wy in range(GY - bh + 30, GY - 40, 52):
                        for wx in range(x + 18, x + bw - 30, 40):
                            if rnd.random() < 0.55:
                                d.rectangle([wx, wy, wx + 16, wy + 26], fill="#FFE9A8")
                x += bw + rnd.randint(4, 22)
        d.rectangle([0, GY, W, H], fill="#3A3A52")
        d.rectangle([0, GY, W, GY + 14], fill="#6B6B8A")
        for lx in range(40, W, 200):
            d.rectangle([lx, GY + 120, lx + 110, GY + 134], fill="#E5E7EB")
        return dict(bg=img, ink="#111111", head="#FFFFFF", env=env)
    if env == "room":
        img = make_gradient("#FFE8C2", "#F6D3A0")
        d = ImageDraw.Draw(img)
        d.rectangle([120, 470, 430, 900], fill="#8B5E3C")
        d.rectangle([140, 490, 410, 880], fill="#9AD8FF")
        d.line([275, 490, 275, 880], fill="#8B5E3C", width=12)
        d.line([140, 685, 410, 685], fill="#8B5E3C", width=12)
        d.rectangle([700, 520, 930, 720], fill="#8B5E3C")
        d.rectangle([718, 538, 912, 702], fill="#FF9AA2")
        d.ellipse([770, 580, 860, 660], fill="#FFD6A5")
        d.rectangle([0, GY, W, H], fill="#B07A4F")
        d.rectangle([0, GY - 26, W, GY + 8], fill="#8B5E3C")
        for lx in range(0, W, 180):
            d.line([lx, GY + 8, lx - 60, H], fill="#9C6841", width=4)
        return dict(bg=img, ink="#111111", head="#FFFFFF", env=env)
    if env in ("night", "night0"):
        img = make_gradient("#0B1026", "#243B7A")
        d = ImageDraw.Draw(img)
        if env == "night":
            d.ellipse([740, 230, 940, 430], fill="#FFF3B0")
            d.ellipse([790, 215, 990, 415], fill="#0F1838")
        d.ellipse([-250, 1150, 800, 1560], fill="#16223F")
        d.ellipse([400, 1180, 1450, 1600], fill="#121C36")
        d.rectangle([0, GY, W, H], fill="#0E172E")
        d.rectangle([0, GY, W, GY + 8], fill="#1E2C52")
        return dict(bg=img, ink="#F5F5F5", head="#FFFFFF", face="#111111", env=env, stars=[(rnd.randint(20, W - 20), rnd.randint(40, 1050), rnd.random() * 6) for _ in range(40)])
    if env == "ocean":
        img = make_gradient("#6EC6FF", "#D2F1FF")
        d = ImageDraw.Draw(img)
        d.ellipse([780, 200, 960, 380], fill="#FFE066")
        d.rectangle([0, 980, W, GY], fill="#1F7FC4")
        d.rectangle([0, GY, W, H], fill="#F2D29B")
        d.rectangle([0, GY, W, GY + 10], fill="#E0B974")
        for k in range(14):
            x, y = rnd.randint(0, W), rnd.randint(GY + 40, H - 40)
            d.ellipse([x, y, x + 26, y + 10], fill="#E6BF82")
        return dict(bg=img, ink="#111111", head="#FFFFFF", env=env)
    if env == "moon":
        img = make_gradient("#05050F", "#1B1038")
        d = ImageDraw.Draw(img)
        d.ellipse([630, 250, 970, 590], fill="#2F80ED")
        for pts in (((700, 330), (780, 300), (820, 360), (760, 410), (700, 390)),
                    ((820, 430), (900, 420), (930, 500), (860, 540), (810, 500))):
            d.polygon(pts, fill="#3DBE5A")
        d.arc([650, 270, 950, 570], 200, 250, fill="#FFFFFF", width=8)
        d.rectangle([0, GY, W, H], fill="#B8BCC2")
        d.rectangle([0, GY, W, GY + 10], fill="#D8DBDF")
        for cx_, cy_, rr in ((180, 1480, 90), (620, 1600, 120), (900, 1450, 70), (400, 1750, 80)):
            d.ellipse([cx_ - rr, cy_ - rr * 0.35, cx_ + rr, cy_ + rr * 0.35], fill="#8E9399")
        return dict(bg=img, ink="#F5F5F5", head="#FFFFFF", face="#111111", env=env,
                    stars=[(rnd.randint(20, W - 20), rnd.randint(40, 1100), rnd.random() * 6) for _ in range(40)])
    th = THEMES[theme]
    top, bot = th["bgs"][si % len(th["bgs"])]
    img = make_gradient(top, bot)
    d = ImageDraw.Draw(img)
    d.line([(160, GY), (920, GY)], fill=blend(bot, th["ink"], 0.35), width=8)
    ink = th["ink"]
    return dict(bg=img, ink=ink, head="#FFFFFF" if ink == "#111111" else "#111827", env="plain",
                deco=blend(bot, ink, 0.07))


def draw_dyn(d, E, t, si):
    env = E["env"]
    if env == "sky":
        for k, (cy, sc, sp) in enumerate([(380, 1.0, 22), (640, 0.7, 14), (250, 0.8, 30)]):
            cx = (k * 430 + t * sp) % (W + 500) - 250
            for dx, dy, r in [(-60, 10, 50), (0, -12, 68), (66, 12, 52)]:
                d.ellipse([cx + (dx - r) * sc, cy + (dy - r) * sc, cx + (dx + r) * sc, cy + (dy + r) * sc], fill="#FFFFFF")
    elif env == "ocean":
        for col, base, amp_, ph, ln in (("#2D9CDB", 1040, 24, 0.0, 90), ("#5BB8F0", 1150, 20, 2.0, 70)):
            pts = [(x, base + amp_ * math.sin(x / ln + t * 2.2 + ph) + 11 * math.sin(x / 47 - t * 3 + ph)) for x in range(0, W + 31, 30)]
            d.polygon(pts + [(W, GY), (0, GY)], fill=col)
        foam = [(x, 1262 + 9 * math.sin(x / 55 + t * 3)) for x in range(0, W + 31, 30)]
        d.line(foam, fill="#FFFFFF", width=10)
    elif env in ("night", "night0", "moon"):
        for x, y, ph in E["stars"]:
            r = 3 + 2.2 * math.sin(t * 3 + ph)
            d.ellipse([x - r, y - r, x + r, y + r], fill="#FFFFFF")
    elif env == "plain":
        for k in range(6):
            ph = k * 1.7 + si
            cx = W * ((k * 0.19 + 0.1 * math.sin(ph + t * 0.4)) % 1)
            cy = 150 + (H - 300) * ((k * 0.37 + 0.05 * math.cos(ph + t * 0.3)) % 1)
            rr = 70 + 45 * (k % 3)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=E["deco"])


# ───────────────────────── text overlays ─────────────────────────
def draw_caption(d, words, t, fpath, base, rtl, upper, si, y=1570, color=None):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.!?؟،,]$", w[0]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    act = chunks[0]
    for ch in chunks:
        if ch[0][1] <= t + 0.03:
            act = ch
    ci = max([i for i, w in enumerate(act) if w[1] <= t + 0.03] or [0])
    color = color or CAP_COLORS[(chunks.index(act) + si) % len(CAP_COLORS)]
    sizes, texts = [], []
    for i, w in enumerate(act):
        txt = shape(w[0].upper() if upper else w[0])
        texts.append(txt)
        k = ease_back((t - w[1]) / 0.16) if i == ci else 0
        sizes.append(base * (1 + 0.22 * k) if i == ci else base)
    gap = base * 0.28
    widths = [font(fpath, s).getlength(tx) for s, tx in zip(sizes, texts)]
    total = sum(widths) + gap * (len(texts) - 1)
    fit = min(1.0, (W - 90) / total)
    sizes = [s * fit for s in sizes]
    widths = [w * fit for w in widths]
    total = sum(widths) + gap * fit * (len(texts) - 1)
    order = list(range(len(texts)))
    if rtl:
        order.reverse()
    x = (W - total) / 2
    for i in order:
        d.text((x, y), texts[i], font=font(fpath, sizes[i]), fill=color if i == ci else "#FFFFFF", anchor="ls",
               stroke_width=max(8, int(sizes[i] / 10)), stroke_fill="#000000")
        x += widths[i] + gap * fit


def draw_headline(d, lines, t, fpath, size=124, y0=290):
    k = ease_back(t / 0.3)
    f = font(fpath, size * (0.55 + 0.45 * k))
    for li, line in enumerate(lines):
        d.text((W / 2, y0 + li * 125), shape(line), font=f, fill="#FFFFFF", anchor="ms",
               stroke_width=11, stroke_fill="#000000")


def draw_impact(img, text, t, fpath, upper):
    if t < 0.12:
        return
    k = ease_back((t - 0.12) / 0.25)
    f = font(fpath, 220 * max(0.25, k))
    lay = Image.new("RGBA", (1040, 420), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((520, 210), shape(text.upper() if upper else text), font=f, fill="#FFE600",
                             anchor="mm", stroke_width=16, stroke_fill="#000000")
    lay = lay.rotate(-8 + 3 * math.sin(t * 14), resample=Image.BILINEAR)
    img.paste(lay, (20, 300), lay)


def camera(img, z, dx, dy):
    w, h = W / z, H / z
    x0 = min(max((W - w) / 2 + dx, 0), W - w)
    y0 = min(max((H - h) / 2 + dy, 0), H - h)
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))


# ───────────────────────── audio ─────────────────────────
def probe_dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "default=nw=1:nk=1", str(path)]).strip())


async def _tts(text, voice, rate, out):
    import edge_tts
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:
        comm = edge_tts.Communicate(text, voice, rate=rate)
    words = []
    with open(out, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                st = ch["offset"] / 1e7
                words.append((ch["text"], st, st + ch["duration"] / 1e7))
    return words


def even_words(text, dur):
    ws = text.split()
    wt = [len(w) + 2 + (4 if re.search(r"[.!?,;:]$", w) else 0) for w in ws]
    tot, out, t = sum(wt) or 1, [], 0.0
    for w, x in zip(ws, wt):
        d = dur * x / tot
        out.append((w, t, t + d))
        t += d
    return out


def to_wav(src, dst, pad):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"apad=pad_dur={pad}",
                    "-ar", str(SR), "-ac", "1", str(dst)], check=True)


_kok = None


def kokoro_model():
    global _kok
    if _kok is None:
        from kokoro_onnx import Kokoro
        mdir = HERE / "models"
        mdir.mkdir(exist_ok=True)
        for n in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
            if not (mdir / n).exists():
                print("Downloading", n, "(one-time)…")
                urllib.request.urlretrieve(KOKORO_BASE + n, mdir / n)
        _kok = Kokoro(str(mdir / "kokoro-v1.0.onnx"), str(mdir / "voices-v1.0.bin"))
    return _kok


def kokoro_scene(text, voice, speed, lang, out):
    """Synthesize sentence-by-sentence: gives exact phrase timings + natural pauses."""
    k = kokoro_model()
    segs = [x for x in re.split(r"(?<=[.!?;:,])\s+", text.strip()) if x]
    parts, words, t = [], [], 0.0
    for i, sg in enumerate(segs):
        x, sr = k.create(sg, voice=voice, speed=speed, lang=KOKORO_LANG.get(lang, "en-us"))
        d = len(x) / sr
        words += [(w, a + t, b + t) for w, a, b in even_words(sg, d)]
        parts.append(x)
        t += d
        gap = 0 if i == len(segs) - 1 else (0.30 if sg[-1] in ".!?" else 0.14)
        if gap:
            parts.append(np.zeros(int(gap * sr), dtype=np.float32))
            t += gap
    x = np.concatenate(parts)
    x = x / max(1e-6, float(np.abs(x).max())) * 0.9
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return words


def eleven_scene(text, voice_id, model, out):
    key = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("Set ELEVENLABS_API_KEY")
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}}
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps(body).encode(),
        headers={"xi-api-key": key, "content-type": "application/json", "User-Agent": "stickman-reels"})
    r = json.load(urllib.request.urlopen(req))
    Path(out).write_bytes(base64.b64decode(r["audio_base64"]))
    al = r["alignment"]
    words, cur, ws, pe = [], "", 0.0, 0.0
    for c, a, b in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if c.isspace():
            if cur:
                words.append((cur, ws, pe))
                cur = ""
        else:
            if not cur:
                ws = a
            cur += c
            pe = b
    if cur:
        words.append((cur, ws, pe))
    return words


OPTS = {"speed": 1.06, "el_model": "eleven_multilingual_v2"}
CACHE = HERE / ".tts_cache"


def synth_cached(engine, text, voice, lang, rate, i, tmp):
    """Synthesis with an on-disk cache (re-renders are instant and ElevenLabs calls are never paid twice)."""
    key = hashlib.sha1(f"{engine}|{voice}|{OPTS['speed']}|{rate}|{OPTS['el_model']}|{lang}|{text}".encode()).hexdigest()[:20]
    CACHE.mkdir(exist_ok=True)
    ext = "wav" if engine == "kokoro" else "mp3"
    raw, meta = CACHE / f"{key}.{ext}", CACHE / f"{key}.json"
    if raw.exists() and meta.exists():
        return raw, [tuple(w) for w in json.load(open(meta))]
    if engine == "kokoro":
        words = kokoro_scene(text, voice, OPTS["speed"], lang, raw)
    elif engine == "elevenlabs":
        words = eleven_scene(text, voice, OPTS["el_model"], raw)
    else:
        words = asyncio.run(_tts(text, voice, rate, raw))
    json.dump(words, open(meta, "w"))
    return raw, words


def make_voice(scenes, voices, default_voice, rate, tmp, engine, lang, pad=0.18):
    infos, wavs = [], []
    Path(tmp).mkdir(parents=True, exist_ok=True)
    for i, sc in enumerate(scenes):
        text, wavp = sc["text"], Path(tmp) / f"s{i}.wav"
        speaker = sc.get("speaker", "narrator" if sc.get("cast") else "hero")
        voice = sc.get("voice") or voices.get(speaker) or voices.get("narrator") or default_voice
        if engine == "none":
            speech = max(1.8, len(text.split()) * 0.36)
            words = even_words(text, speech)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                            "-t", f"{speech + pad}", str(wavp)], check=True)
        elif engine in ("espeak", "flite"):  # offline fallbacks, robotic — preview only
            raw = Path(tmp) / f"e{i}.wav"
            if engine == "flite":
                subprocess.run(["flite", "-voice", "slt", "--setf", "duration_stretch=0.9", "-t", text, "-o", str(raw)], check=True)
            else:
                subprocess.run(["espeak-ng", "-v", lang, "-s", "150", "-w", str(raw), text], check=True)
            speech = probe_dur(raw)
            words = even_words(text, speech)
            to_wav(raw, wavp, pad)
        else:
            raw, words = synth_cached(engine, text, voice, lang, rate, i, tmp)
            speech = probe_dur(raw)
            words = words or even_words(text, speech)
            to_wav(raw, wavp, pad)
        infos.append(dict(speech=speech, dur=speech + pad, words=words, speaker=speaker))
        wavs.append(wavp)
    return infos, wavs


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def add(out, seg_, at):
    at = int(at * SR)
    if at >= len(out):
        return
    e = min(len(out), at + len(seg_))
    out[at:e] += seg_[:e - at]


def sfx_whoosh():
    n = int(SR * 0.38)
    x = np.random.default_rng(3).normal(size=n).astype(np.float32)
    k = np.ones(14) / 14
    x = np.convolve(np.convolve(x, k, "same"), k, "same")
    x *= np.sin(np.linspace(0, np.pi, n)) ** 2
    return x / (np.abs(x).max() + 1e-9)


def sfx_pop():
    t = np.arange(int(SR * 0.2)) / SR
    ph = 2 * np.pi * np.cumsum(600 + 1500 * t / 0.2) / SR
    return (np.sin(ph) * np.exp(-t * 20)).astype(np.float32)


def sfx_boom():
    t = np.arange(int(SR * 0.6)) / SR
    ph = 2 * np.pi * np.cumsum(40 + 90 * np.exp(-t * 14)) / SR
    return (np.sin(ph) * np.exp(-t * 6)).astype(np.float32)


def synth_music(dur, bpm=100):
    out = np.zeros(int(dur * SR) + SR, dtype=np.float32)
    beat = 60 / bpm
    chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]   # Am F C G
    fq = lambda m: 440 * 2 ** ((m - 69) / 12)
    tk = np.arange(int(0.28 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-tk * 28)) / SR) * np.exp(-tk * 13)
    th = np.arange(int(0.05 * SR)) / SR
    hat = np.random.default_rng(5).normal(size=len(th)) * np.exp(-th * 90) * 0.5
    tp = np.arange(int(0.3 * SR)) / SR
    for b in range(int(dur / (4 * beat)) + 2):
        ch = chords[b % 4]
        L = int(4 * beat * SR)
        tt = np.arange(L) / SR
        env = np.minimum(1, tt / 0.35) * np.minimum(1, (4 * beat - tt) / 0.3)
        pad = sum(np.sin(2 * np.pi * fq(m) * tt) + 0.5 * np.sin(2 * np.pi * fq(m) * 1.004 * tt + 1) for m in ch) * env * 0.05
        bass = np.sin(2 * np.pi * fq(ch[0] - 24) * tt) * env * 0.2
        add(out, (pad + bass).astype(np.float32), b * 4 * beat)
        for k in range(4):
            if k % 2 == 0:
                add(out, kick.astype(np.float32) * 0.55, b * 4 * beat + k * beat)
            add(out, hat.astype(np.float32) * 0.16, b * 4 * beat + (k + 0.5) * beat)
        for k in range(8):
            m = ch[(k * 2 + b) % 3] + 12
            pl = np.sin(2 * np.pi * fq(m) * tp) * np.exp(-tp * 9) * 0.07
            add(out, pl.astype(np.float32), b * 4 * beat + k * beat / 2)
    return out[:int(dur * SR)]


def build_mix(wavs, infos, tmp, music, no_music, no_sfx, scenes):
    voice = np.concatenate([read_wav(w) for w in wavs])
    total = len(voice) / SR
    mix = voice.copy()
    if not no_music:
        if music:
            mw = Path(tmp) / "m.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", music, "-ar", str(SR), "-ac", "1", str(mw)], check=True)
            m = read_wav(mw)
            m = np.tile(m, int(len(voice) / max(1, len(m))) + 1)[:len(voice)]
            m = m / (np.abs(m).max() + 1e-9) * 0.35
        else:
            m = synth_music(total + 0.5)[:len(voice)]
            m = m / (np.abs(m).max() + 1e-9) * 0.38
        mix[:len(m)] += m * 0.55
    if not no_sfx:
        st = 0.0
        wh, po, bo = sfx_whoosh(), sfx_pop(), sfx_boom()
        for i, (sc, inf) in enumerate(zip(scenes, infos)):
            if i > 0:
                add(mix, wh * 0.30, st - 0.04)
            if sc.get("prop"):
                add(mix, po * 0.30, st + 0.12)
            if sc.get("impact"):
                add(mix, bo * 0.55, st + 0.12)
            st += inf["dur"]
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    out = Path(tmp) / "mix.wav"
    write_wav(out, mix)
    return out, voice


def amp_envelope(voice, nframes):
    spf = SR // FPS
    n = min(nframes, len(voice) // spf)
    rms = np.sqrt((voice[:n * spf].reshape(n, spf) ** 2).mean(1))
    ref = np.percentile(rms[rms > 1e-3], 85) if (rms > 1e-3).any() else 1
    a = np.clip(rms / ref, 0, 1)
    a = np.convolve(a, [0.25, 0.5, 0.25], "same")
    return np.concatenate([a, np.zeros(nframes - n)])


# ───────────────────────── render ─────────────────────────
_CTX = {}


def layout(n):
    """x positions + auto scale for n characters on screen."""
    if n <= 1:
        return [540], 1.0
    if n == 2:
        return [330, 760], 0.86
    return [215, 540, 865], 0.7


def prep_scene(C, si):
    sc, spec = C["scenes"][si], C["spec"]
    env = sc.get("env") or ENV_CYCLE[si % len(ENV_CYCLE)]
    E = make_env(env, si, C["theme"])
    cast_in = sc.get("cast")
    if not cast_in:   # old single-character format
        cast_in = {"hero": {"pose": sc.get("pose", "talk"), "face": sc.get("face"), "prop": sc.get("prop")}}
    speaker = C["infos"][si]["speaker"]
    names = list(cast_in)
    xs, auto = layout(len(names))
    cast = []
    for i, nm in enumerate(names):
        ci = cast_in[nm]
        cd = C["chars"].get(nm, C["chars"].get("hero", {}))
        flip = ci.get("flip", len(names) > 1 and i == len(names) - 1)
        cast.append(dict(
            name=nm, cd=cd, x=ci.get("x", xs[i]), s=cd.get("scale", 1.0) * auto, flip=flip,
            pose=ci.get("pose") or ("talk" if nm == speaker else "idle"), face=ci.get("face"),
            prop=ci.get("prop"), ps=ci.get("prop_scale", 1.0),
            pside=ci.get("prop_side", (-1 if flip else 1) if len(names) == 1 else (1 if flip else -1)),
            speaking=(nm == speaker)))
    if len(names) == 1 and not sc.get("cast"):
        cast[0]["pside"] = 1
    sp = next((c for c in cast if c["speaking"]), None)
    cap_color = sp["cd"].get("cap_color") if sp else None
    return dict(E=E, cast=cast, speaker_x=sp["x"] if sp else 540, cap_color=cap_color,
                hl=(wrap_lines(sc["headline"].upper() if C["upper"] else sc["headline"], font(C["f_head"], 124), W - 140)
                    if sc.get("headline") else []))


def compose(C, si, fi, pr, gframe):
    sc, info = C["scenes"][si], C["infos"][si]
    t = fi / FPS
    E = pr["E"]
    ink = E["ink"]
    img = E["bg"].copy()
    d = ImageDraw.Draw(img)
    draw_dyn(d, E, t, si)
    k = 0.82 + 0.18 * ease_back(t / 0.3)
    props = []
    for ch in pr["cast"]:
        amp = float(C["amps"][gframe]) if (ch["speaking"] and t < info["speech"]) else 0.0
        layer, hc = render_char(ch["cd"], ch["pose"], ch["face"], t, amp, ink, E["head"], E.get("face", ink), ch["flip"])
        s = ch["s"] * k
        hcx = hc[0]
        if ch["flip"]:
            layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
            hcx = 1080 - hc[0]
        w, h = int(LW_ * s), int(LH_ * s)
        small = layer.reduce(SS) if (w == LW_ and h == LH_) else layer.resize((w, h), Image.BILINEAR)
        img.paste(small, (int(ch["x"] - (540 - LX0) * s), int(GY - (GY - LY0) * s)), small)
        if ch["prop"]:
            gx, gy = ch["x"] + (hcx - 540) * s, GY - (GY - hc[1]) * s
            props.append((ch, gx + ch["pside"] * 215 * s, gy - 30 * s))
    for ch, px, py in props:
        pl = prop_layer(ch["prop"], t, ink, C["f_prop"])
        ps = int(PL * ch["ps"] * k)
        pl = pl.resize((ps, ps), Image.BILINEAR)
        img.paste(pl, (int(px - ps / 2), int(py - ps / 2)), pl)
    if sc.get("impact"):
        draw_impact(img, sc["impact"], t, C["f_imp"], C["upper"])
    # camera: slow push-in, punch on cut, pan toward the speaker, shake on shock/angry/hook
    z = 1.04 + 0.05 * (t / info["dur"]) + (0.07 if si else 0.04) * max(0, 1 - t / 0.25)
    shaky = sc.get("shake") or any(c["pose"] in ("shock", "angry") for c in pr["cast"])
    sh = 9 * math.exp(-t * 2.5) if shaky else 0
    pan = (pr["speaker_x"] - 540) * 0.1 * min(1, t / 0.4)
    img = camera(img, z, pan + (sh * math.sin(t * 61) if sh else 0), sh * math.cos(t * 53) if sh else 0)
    d = ImageDraw.Draw(img)
    if pr["hl"]:
        draw_headline(d, pr["hl"], t, C["f_head"])
    draw_caption(d, info["words"], t, C["f_cap"], 118 if not C["rtl"] else 100, C["rtl"], C["upper"], si, color=pr["cap_color"])
    if si > 0 and t < 0.16:   # flash transition
        img = Image.blend(img, Image.new("RGB", (W, H), "white"), 0.75 * (1 - t / 0.16))
    return img


def render_scene_job(si):
    C = _CTX
    out = C["work"] / f"seg{si:02d}.mp4"
    if out.exists():
        return si
    part = C["work"] / f"seg{si:02d}.part.mp4"
    pr = prep_scene(C, si)
    a, b = C["bounds"][si], C["bounds"][si + 1]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", str(part)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(b - a):
        ff.stdin.write(compose(C, si, fi, pr, a + fi).tobytes())
    ff.stdin.close()
    ff.wait()
    os.replace(part, out)
    return si


def main_render(a):
    spec = json.load(open(a.script, encoding="utf-8"))
    if spec.get("mode") == "legend":
        import legend
        legend.bind(sys.modules[__name__])
        return legend.run(a, spec)
    scenes = spec["scenes"]
    lang = spec.get("lang", "en")
    rtl = lang in ("ar", "he", "fa", "ur") or has_ar(scenes[0]["text"])
    engine = "none" if a.no_tts else a.engine
    if engine == "auto":
        engine = "kokoro" if (lang in KOKORO_LANG and importlib.util.find_spec("kokoro_onnx")) else "edge"
    print("› voice engine:", engine, flush=True)
    OPTS.update(speed=a.speed, el_model=a.el_model)
    defaults = {"kokoro": KOKORO_VOICES.get(lang, "af_heart"), "edge": VOICES.get(lang, VOICES["en"]),
                "elevenlabs": os.environ.get("ELEVENLABS_VOICE_ID", EL_DEFAULT_VOICE)}
    default_voice = a.voice or spec.get("voice_" + engine) or defaults.get(engine, "")
    voices = {} if a.voice else dict(spec.get("voices", {}))
    theme = a.theme or spec.get("theme", "light")
    chars = spec.get("characters") or {"hero": spec.get("character", {})}
    if rtl:
        f_cap = f_head = f_imp = font_path("tajawal", a.font)
        f_prop = font(f_cap, 210)
    else:
        f_cap = f_head = font_path("anton", a.font)
        f_imp = font_path("bangers")
        f_prop = font(f_imp, 210)
    key = hashlib.md5((json.dumps(spec, sort_keys=True) + f"{engine}{a.voice}{a.speed}{a.rate}{theme}{a.music}"
                       f"{a.no_music}{a.no_sfx}v4").encode()).hexdigest()[:10]
    work = Path(a.work) if a.work else HERE / ".work" / key
    work.mkdir(parents=True, exist_ok=True)
    print("› audio…", flush=True)
    infos, wavs = make_voice(scenes, voices, default_voice, a.rate, work / "audio", engine, lang)
    audio, voice_arr = build_mix(wavs, infos, work, a.music, a.no_music, a.no_sfx, scenes)
    cum, bounds = 0.0, [0]
    for inf in infos:
        cum += inf["dur"]
        bounds.append(int(round(cum * FPS)))
    amps = amp_envelope(voice_arr, bounds[-1] + 5)
    _CTX.update(scenes=scenes, spec=spec, infos=infos, chars=chars, theme=theme, rtl=rtl, upper=not rtl, f_cap=f_cap,
                f_head=f_head, f_imp=f_imp, f_prop=f_prop, work=work, bounds=bounds, amps=amps)
    n = len(scenes)
    todo = [i for i in range(n) if not (work / f"seg{i:02d}.mp4").exists()]
    print(f"› video: {n - len(todo)}/{n} scenes cached, rendering {len(todo)} ({bounds[-1] / FPS:.1f}s total)", flush=True)
    t0 = time.time()
    jobs = a.jobs or os.cpu_count() or 1
    if jobs > 1 and len(todo) > 1 and not a.budget:
        with mp.Pool(jobs) as pool:
            for si in pool.imap_unordered(render_scene_job, todo):
                print(f"  scene {si + 1}/{n} ✓", flush=True)
    else:
        for si in todo:
            if a.budget and time.time() - t0 > a.budget:
                break
            render_scene_job(si)
            print(f"  scene {si + 1}/{n} ✓  ({time.time() - t0:.0f}s)", flush=True)
    missing = [i for i in range(n) if not (work / f"seg{i:02d}.mp4").exists()]
    if missing:
        print(f"⏸ time budget reached — {len(missing)} scenes left. Run the same command again to continue.")
        sys.exit(3)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{(work / f'seg{i:02d}.mp4').resolve()}'\n" for i in range(n)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", a.out], check=True)
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("✔ saved:", a.out)


# ───────────────────────── script generation (Claude API) ─────────────────────────
GEN_PROMPT = """You write scripts for faceless stickman YouTube Shorts (~60 seconds) that tell a small STORY with two characters and a narrator, in the style of top viral channels: fast, visual, curiosity-driven, with real facts.
Topic: {topic}
Narration language: {lang_name}
Return ONLY valid JSON, no markdown:
{{"title": "...", "lang": "{lang}",
 "characters": {{"kid": {{"scale": 0.84, "shirt": "#FF7A00", "hair": "spiky", "hair_color": "#4A2C17", "cap_color": "#FFE600"}},
                "prof": {{"scale": 1.0, "shirt": "#FFFFFF", "hair": "tufts", "hair_color": "#E5E7EB", "glasses": true, "mustache": true, "bowtie": true, "cap_color": "#4DD2FF"}}}},
 "voices": {{"narrator": "af_heart", "kid": "am_liam", "prof": "bm_george"}},
 "scenes": [
  {{"speaker": "narrator" | "kid" | "prof", "text": "spoken line, 3-14 words", "env": one of {envs},
    "headline": optional on-screen title (max 4 words), "impact": optional punch word like "WOW!" (max 2 words), "shake": optional true for dramatic beats,
    "cast": {{"kid": {{"pose": one of {poses}, "face": optional one of ["smile","big","sad","think","surprised","angry","scared","laugh","blush"],
                      "prop": optional one of {props}}}, "prof": {{...}}}}}}
 ]}}
Rules: about {n} scenes, ~170 words total. Scene 1 is a scroll-stopping HOOK: a shocking claim or question plus a promise ("the third thing will terrify you").
Story arc: hook -> panic/curiosity -> 3 surprising facts explained as a dialogue (kid asks, prof answers) -> twist or funny reveal -> short call to action.
Facts must be accurate and kid-friendly. Change env or poses every scene. Characters not speaking should react (scared, think, shock, laugh).
Use env "night0" for a night without the Moon, "moon" for the Moon surface, "ocean" for beach. No emojis in text."""


GEN_LEGEND_PROMPT = """You write scripts for a faceless YouTube Shorts channel about urban legends and folklore, in a dark illustrated horror-comic style (~55 seconds).
Topic: {topic}
Return ONLY valid JSON, no markdown:
{{"mode": "legend", "title": "...", "lang": "en", "speed": 0.9, "voices": {{"narrator": "am_onyx"}},
 "scenes": [
  {{"text": "narration, 6-16 words", "art": one of ["school","corridor","corridor_figure","bathroom","bathroom_empty","stall","eyes","girl","forest"] (placeholder art used when no image exists),
    "image_prompt": "a detailed illustration prompt for this scene (no text in the image)",
    "camera": one of ["creep","zoom_in","zoom_out","pan_left","pan_right","pan_up","pan_down","static"],
    "tag": optional small tag like "Japanese Legend" (first scene only), "title": optional big red title (max 3 words),
    "label": optional short white label (1-2 words), "arrow": optional [x, y, angle] fractions of the screen + angle in degrees,
    "sfx": optional list from ["knock","sting","whisper","creak","boom"], "scare": optional true for a jump-scare beat (max 2), "shake": optional true}}
 ]}}
Rules: about {n} scenes. Scene 1 is a hook that creates dread in one sentence ("Never knock on the third stall."). Tell the legend in escalating beats,
mention that versions differ, and only use facts you are sure about (name places, dates and rules only if well documented).
No gore, no real tragedies, no self-harm. Dread comes from atmosphere and suggestion. Last scene is a short call to action ("Follow for the next legend").
Final scene may use "collage": true with "panels": [{{"art": "...", "label": "..."}}, x3] and "title": "LEGENDS"."""


def main_gen(a):
    key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("Set ANTHROPIC_API_KEY")
    lang_name = {"ar": "Arabic (Modern Standard, simple)", "en": "English", "fr": "French", "es": "Spanish"}.get(a.lang, a.lang)
    prompt = (GEN_LEGEND_PROMPT.format(topic=a.topic, n=a.scenes) if a.style == "legend" else
              GEN_PROMPT.format(topic=a.topic, lang=a.lang, lang_name=lang_name, poses=POSES, envs=ENVS, props=PROPS, n=a.scenes))
    body = {"model": a.model, "max_tokens": 5000, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    txt = json.load(urllib.request.urlopen(req))["content"][0]["text"]
    data = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("✔ script saved:", a.out)


def cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="generate a script JSON with Claude")
    g.add_argument("topic")
    g.add_argument("--lang", default="en")
    g.add_argument("--style", choices=["story", "legend"], default="story", help="story = stickman dialogue, legend = dark horror legends")
    g.add_argument("--scenes", type=int, default=19)
    g.add_argument("--model", default="claude-sonnet-5-5")
    g.add_argument("-o", "--out", default="script.json")
    pp = sub.add_parser("prompts", help="write the image-generation prompts of a legend script to a text file")
    pp.add_argument("script")
    pp.add_argument("-o", "--out", default="prompts.txt")
    r = sub.add_parser("render", help="render a script JSON to mp4")
    r.add_argument("--images", help="folder with your own scene images named 01.png, 02.png … (legend mode)")
    r.add_argument("--imagegen", action="store_true", help="generate missing scene images via an image API (needs IMAGE_API_KEY)")
    r.add_argument("script")
    r.add_argument("-o", "--out", default="reel.mp4")
    r.add_argument("--theme", choices=list(THEMES))
    r.add_argument("--voice", help="voice name/id for the chosen engine (e.g. af_heart, am_michael, bm_george)")
    r.add_argument("--rate", default="+6%", help='speech speed e.g. "+10%%"')
    r.add_argument("--music", help="your own background music file (default: built-in synthesized loop)")
    r.add_argument("--no-music", action="store_true")
    r.add_argument("--no-sfx", action="store_true")
    r.add_argument("--font", help="override caption font (e.g. an Arabic font)")
    r.add_argument("--engine", choices=["auto", "kokoro", "edge", "elevenlabs", "flite", "espeak"], default="auto",
                   help="kokoro = free, natural, offline (best default); elevenlabs = premium (API key); "
                        "edge = free online (also Arabic); flite/espeak = robotic offline preview")
    r.add_argument("--speed", type=float, default=1.06, help="kokoro speaking speed (1.0 = normal)")
    r.add_argument("--el-model", default="eleven_multilingual_v2", help="ElevenLabs model id")
    r.add_argument("--no-tts", action="store_true", help="silent preview")
    r.add_argument("--jobs", type=int, default=0, help="parallel scene renderers (default: all CPU cores)")
    r.add_argument("--budget", type=float, default=0, help="stop after N seconds (resume by re-running); sequential mode")
    r.add_argument("--work", help="working directory (default: .work/<hash>, enables resume)")
    r.add_argument("--keep", action="store_true", help="keep the working directory after success")
    a = ap.parse_args()
    if a.cmd == "gen":
        main_gen(a)
    elif a.cmd == "prompts":
        import legend
        legend.bind(sys.modules[__name__])
        legend.write_prompts(json.load(open(a.script, encoding="utf-8")), a.out)
    else:
        main_render(a)


if __name__ == "__main__":
    cli()
