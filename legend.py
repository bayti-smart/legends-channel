"""
Legend mode — dark illustrated horror-legend reels.

Scenes use (in this order): your own image file / images/NN.png / an AI image generator / built-in procedural art.
Adds: slow camera (creep, shake, knock kicks), fog, flicker, film grain, vignette, red italic titles,
label tags, red arrows, red-highlight captions, and a dark ambient score with knocks, stings and whispers.
"""
import base64, hashlib, json, math, multiprocessing as mp, os, random, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

import legend_art as la

MR = None                      # the make_reel module (set by bind)
W, H, FPS, SR = 1080, 1920, 30, 44100
CW, CH = la.CW, la.CH
RED = "#E11414"
HERE = Path(__file__).resolve().parent
IMG_STYLE = ("2D stylized horror comic illustration with thick black ink outlines and flat cel shading, muted teal and green palette with a single red accent, "
             "grainy paper texture, dark moody lighting, vertical 9:16 composition, NOT a photograph, NOT photorealistic, no text, no watermark")
_CTX = {}
_cache = {}


def bind(mod):
    global MR
    MR = mod


# ───────────────────────── images ─────────────────────────
def cover(img, size):
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _image_cache_path(full_prompt):
    cdir = HERE / ".image_cache"
    cdir.mkdir(exist_ok=True)
    return cdir / (hashlib.sha1(full_prompt.encode()).hexdigest()[:16] + ".png")


def _valid_image(path):
    try:
        if Path(path).stat().st_size < 8000:
            return False
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def _fetch_pollinations(prompt, out, seed, w=1024, h=1536):
    import urllib.parse
    base = os.environ.get("POLLINATIONS_BASE") or "https://image.pollinations.ai"
    ref = os.environ.get("POLLINATIONS_REFERRER") or "legends-channel"
    headers = {"User-Agent": "legends-channel/1.0", "Referer": "https://" + ref}
    if os.environ.get("POLLINATIONS_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["POLLINATIONS_API_KEY"]
    last = "no attempt"
    for model in ("flux", "turbo"):
        url = (f"{base}/prompt/" + urllib.parse.quote(prompt[:700]) +
               f"?width={w}&height={h}&model={model}&nologo=true&private=true&enhance=false&seed={seed}&referrer={urllib.parse.quote(ref)}")
        for attempt in range(3):
            try:
                r = requests.get(url, headers=headers, timeout=150)
            except requests.RequestException as e:
                last = f"{model}: {type(e).__name__}"
                time.sleep(12)
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 8000:
                Path(out).write_bytes(r.content)
                if _valid_image(out):
                    return True, f"{model} ok"
                last = f"{model}: bad image"
            else:
                last = f"{model}: HTTP {r.status_code}"
                wait = r.headers.get("retry-after", "")
                time.sleep(int(wait) if wait.isdigit() else (25 if r.status_code == 429 else 12))
    return False, last


def gen_image(prompt, out):
    """Pollinations (free; IMAGE_PROVIDER=pollinations) or any OpenAI-compatible endpoint (IMAGE_API_KEY)."""
    if os.environ.get("IMAGE_PROVIDER") == "pollinations":
        ok, why = _fetch_pollinations(prompt, out, int(hashlib.sha1(prompt.encode()).hexdigest()[:6], 16))
        if not ok:
            raise RuntimeError(why)
        return
    key = os.environ.get("IMAGE_API_KEY")
    if not key:
        raise RuntimeError("no IMAGE_API_KEY")
    base = os.environ.get("IMAGE_API_BASE", "https://api.openai.com/v1")
    body = {"model": os.environ.get("IMAGE_MODEL", "gpt-image-1"), "prompt": prompt, "size": "1024x1536", "n": 1}
    req = urllib.request.Request(base + "/images/generations", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    item = json.load(urllib.request.urlopen(req, timeout=240))["data"][0]
    if item.get("b64_json"):
        Path(out).write_bytes(base64.b64decode(item["b64_json"]))
    else:
        urllib.request.urlretrieve(item["url"], out)


def ensure_image(prompt, style):
    """Returns the cached image path for this prompt, generating it if needed (None if it keeps failing)."""
    full = prompt + ". " + style
    p = _image_cache_path(full)
    fail = p.with_suffix(".fail")
    if p.exists() and _valid_image(p):
        return p, "cached"
    if fail.exists():
        return None, "skipped (failed before)"
    try:
        gen_image(full, p)
        return p, "generated"
    except Exception as e:
        p.unlink(missing_ok=True)
        fail.write_text(str(e)[:200])
        return None, str(e)[:120]


def prefetch_images(scenes, spec):
    """One image at a time, spaced out (free services reject parallel bursts), before the parallel video render starts."""
    style = spec.get("image_style", IMG_STYLE)
    todo = [(i, sc["image_prompt"]) for i, sc in enumerate(scenes) if sc.get("image_prompt") and not sc.get("collage")]
    ok, report = 0, []
    for k, (i, prompt) in enumerate(todo):
        t0 = time.time()
        p, why = ensure_image(prompt, style)
        ok += bool(p)
        report.append(f"{i + 1}:{'OK' if p else 'FAIL'}({why[:40]},{time.time() - t0:.0f}s)")
        print(f"  image {k + 1}/{len(todo)} scene {i + 1}: {why}", flush=True)
        if p and why == "generated" and k < len(todo) - 1:
            time.sleep(float(os.environ.get("IMAGE_GAP_SECONDS") or "6"))
    print(f"::notice title=Images::{ok}/{len(todo)} generated | " + " ".join(report)[:900])
    return ok, len(todo)


def scene_art(C, si, name=None, sc=None):
    """Returns (RGB image CWxCH, meta). Cached per process."""
    sc = sc or C["scenes"][si]
    key = (si, name)
    if key in _cache:
        return _cache[key]
    path = None
    if name is None:
        path = sc.get("image")
        d = C.get("images_dir")
        if not path and d:
            for ext in ("png", "jpg", "jpeg", "webp"):
                p = Path(d) / f"{si + 1:02d}.{ext}"
                if p.exists():
                    path = str(p)
                    break
        if not path and C.get("imagegen") and sc.get("image_prompt"):
            p, _ = ensure_image(sc["image_prompt"], C["spec"].get("image_style", IMG_STYLE))
            path = str(p) if p else None
    if path:
        img = cover(Image.open(path).convert("RGB"), (CW, CH))
        img = ImageEnhance.Color(img).enhance(0.8)
        img = ImageEnhance.Brightness(img).enhance(0.92)
        res = (img, {})
    else:
        res = la.make_art(name or sc.get("art", "school"), seed=si + 1)
    _cache[key] = res
    return res


# ───────────────────────── post-processing ─────────────────────────
def vignette():
    if "vig" not in _cache:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx - W / 2) / (W * .62)) ** 2 + ((yy - H / 2) / (H * .62)) ** 2)
        v = .34 + .66 * np.clip(1.15 - d ** 1.7, 0, 1)
        _cache["vig"] = Image.fromarray((v * 255).astype(np.uint8)).convert("RGB")
    return _cache["vig"]


def grain(i):
    if "grain" not in _cache:
        rng = np.random.default_rng(7)
        # coarse + subtle grain: looks like film but stays cheap to encode (fine noise explodes the bitrate)
        _cache["grain"] = [Image.fromarray(rng.normal(128, 7, (H // 3, W // 3)).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR).convert("RGB")
                           for _ in range(6)]
    return _cache["grain"][i % 6]


def fog_mask():
    if "fog" not in _cache:
        rnd = random.Random(5)
        m = Image.new("L", (W * 2, H), 0)
        d = ImageDraw.Draw(m)
        for _ in range(16):
            x, y = rnd.uniform(0, 2 * W), rnd.uniform(.55, .95) * H
            rw, rh = rnd.uniform(.2, .45) * W, rnd.uniform(.02, .05) * H
            d.ellipse([x - rw, y - rh, x + rw, y + rh], fill=52)
        _cache["fog"] = m.filter(ImageFilter.GaussianBlur(50))
    return _cache["fog"]


def glow_sprite():
    if "spr" not in _cache:
        yy, xx = np.mgrid[-1:1:128j, -1:1:128j]
        v = np.clip(1 - np.sqrt(xx ** 2 + yy ** 2), 0, 1) ** 2
        _cache["spr"] = Image.fromarray((v * 255).astype(np.uint8))
    return _cache["spr"]


def add_glow(img, x, y, r, color, k):
    r = int(r)
    if r < 3 or k <= .02:
        return
    sp = glow_sprite().resize((2 * r, 2 * r), Image.BILINEAR).point(lambda v: int(min(255, v * k)))
    x0, y0 = int(x - r), int(y - r)
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + 2 * r), min(H, y0 + 2 * r)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    sp = sp.crop((cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0))
    reg = img.crop((cx0, cy0, cx1, cy1))
    add = Image.composite(Image.new("RGB", reg.size, color), Image.new("RGB", reg.size, (0, 0, 0)), sp)
    img.paste(ImageChops.add(reg, add), (cx0, cy0))


def glitch(img, fi, strength=1.0):
    rng = random.Random(fi * 31 + 7)
    r, g, b = img.split()
    sh = int(16 * strength)
    img = Image.merge("RGB", (ImageChops.offset(r, sh, 0), g, ImageChops.offset(b, -sh, 0)))
    for _ in range(6):
        y, h = rng.randint(0, H - 100), rng.randint(20, 90)
        img.paste(img.crop((0, y, W, y + h)), (rng.randint(-70, 70), y))
    return img


# ───────────────────────── text / graphics overlays ─────────────────────────
def italic(text, size, fill, stroke=8, stroke_fill="#000000", shear=.22):
    key = ("it", text, int(size), fill, stroke)
    if key not in _cache:
        f = MR.font(_CTX["font"], int(size))
        w, h = int(f.getlength(text)) + stroke * 2 + int(size * shear) + 24, int(size * 1.5)
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((12 + stroke, h * .75), text, font=f, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=stroke_fill)
        _cache[key] = lay.transform(lay.size, Image.AFFINE, (1, shear, -shear * h * .75, 0, 1, 0), Image.BILINEAR)
    return _cache[key]


def paste_center(img, lay, cx, cy):
    img.paste(lay, (int(cx - lay.width / 2), int(cy - lay.height / 2)), lay)


def draw_title(img, text, cy_frac, t, size=170, color=RED, jitter=0.0):
    k = MR.ease_back(t / .3)
    s = size * (.55 + .45 * k)
    jx = jitter * math.sin(t * 70) * 5
    lay = italic(text.upper(), s, color, stroke=max(6, int(s / 14)))
    if lay.width > W - 70:
        s2 = s * (W - 70) / lay.width
        lay = italic(text.upper(), s2, color, stroke=max(6, int(s2 / 14)))
    paste_center(img, lay, W / 2 + jx, cy_frac * H)


def draw_label(img, text, x_frac, y_frac, t, size=54):
    k = min(1, MR.ease_back((t - .1) / .25))
    if k <= 0:
        return
    paste_center(img, italic(text.upper(), size * (.6 + .4 * k), "#FFFFFF", stroke=6), x_frac * W, y_frac * H)


def draw_tag(img, text, y_frac=.085):
    f = MR.font(_CTX["font"], 44)
    tw = int(f.getlength(text.upper())) + 56
    box = Image.new("RGBA", (tw, 84), (0, 0, 0, 165))
    ImageDraw.Draw(box).text((28, 44), text.upper(), font=f, fill="#FFFFFF", anchor="lm")
    img.paste(box, (50, int(y_frac * H)), box)


def draw_arrow(img, x, y, ang, t):
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    off = 14 * math.sin(t * 7)
    x, y = x - ux * off, y - uy * off
    L = 190
    tx, ty = x - ux * L, y - uy * L
    d = ImageDraw.Draw(img)
    base = (x - ux * 64, y - uy * 64)
    head = [(x, y), (base[0] + nx * 34, base[1] + ny * 34), (base[0] - nx * 34, base[1] - ny * 34)]
    d.line([(tx, ty), base], fill="#000000", width=20)
    d.polygon(head, fill="#000000")
    d.line([(tx, ty), base], fill=RED, width=11)
    inner = [(x - ux * 7, y - uy * 7), (base[0] + nx * 22, base[1] + ny * 22), (base[0] - nx * 22, base[1] - ny * 22)]
    d.polygon(inner, fill=RED)


# ───────────────────────── camera ─────────────────────────
MODES = {"zoom_in": (1.06, 1.30), "zoom_out": (1.30, 1.06), "pan_left": (1.22, 1.22), "pan_right": (1.22, 1.22),
         "pan_up": (1.2, 1.2), "pan_down": (1.2, 1.2), "static": (1.15, 1.18), "creep": (1.10, 1.24)}


def camera_box(sc, t, dur, meta, knocks):
    mode = sc.get("camera", "creep")
    z0, z1 = MODES[mode]
    p = t / max(dur, .1)
    z = z0 + (z1 - z0) * p
    cx, cy = .5, .5
    hot = meta.get("hot")
    if hot and sc.get("focus", True) and mode in ("zoom_in", "creep"):
        cx, cy = .5 + (hot[0] / CW - .5) * .7 * p, .5 + (hot[1] / CH - .5) * .7 * p
    elif hot and sc.get("focus", True) and mode == "zoom_out":
        cx, cy = .5 + (hot[0] / CW - .5) * .7 * (1 - p), .5 + (hot[1] / CH - .5) * .7 * (1 - p)
    m = (1 - 1 / z) / 2 * .85
    if mode == "pan_left":
        cx = .5 + m - 2 * m * p
    elif mode == "pan_right":
        cx = .5 - m + 2 * m * p
    elif mode == "pan_up":
        cy = .5 + m - 2 * m * p
    elif mode == "pan_down":
        cy = .5 - m + 2 * m * p
    for tk in knocks:
        if 0 <= t - tk < .5:
            z += .07 * math.exp(-(t - tk) * 11)
    dx = dy = 0.0
    if sc.get("scare") or sc.get("shake"):
        sh = 16 * math.exp(-t * 3.2)
        dx, dy = sh * math.sin(t * 67), sh * math.cos(t * 59)
    w, h = CW / z, CH / z
    x0 = min(max(cx * CW - w / 2 + dx, 0), CW - w)
    y0 = min(max(cy * CH - h / 2 + dy, 0), CH - h)
    return (x0, y0, x0 + w, y0 + h), z


# ───────────────────────── composition ─────────────────────────
def collage_bg():
    if "cbg" not in _cache:
        img = la.grad("#0D0406", "#2A0709", (W, H))
        d = ImageDraw.Draw(img)
        for x in range(0, W, 54):
            d.line([x, 0, x, H], fill=(58, 12, 14), width=2)
        for y in range(0, H, 54):
            d.line([0, y, W, y], fill=(58, 12, 14), width=2)
        _cache["cbg"] = img
    return _cache["cbg"].copy()


def compose_collage(C, si, t, dur):
    sc = C["scenes"][si]
    img = collage_bg()
    d = ImageDraw.Draw(img)
    panels = sc["panels"]
    pw, ph, gap = 316, 640, 22
    x0 = (W - (len(panels) * pw + (len(panels) - 1) * gap)) // 2
    y0 = 360
    for i, pn in enumerate(panels):
        art, meta = scene_art(C, si, name=pn["art"], sc={"art": pn["art"]})
        z = 1.05 + .07 * t / max(dur, .1) + .02 * i
        h = CH / z
        w = h * pw / ph
        hot = meta.get("hot") or (CW / 2, CH / 2)
        cx = min(max(hot[0], w / 2), CW - w / 2)
        cy = min(max(hot[1], h / 2), CH - h / 2)
        tile = art.resize((pw, ph), Image.BILINEAR, box=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        k = MR.ease_back((t - .12 * i) / .35)
        yy = int(y0 + (1 - k) * 90)
        px = x0 + i * (pw + gap)
        d.rectangle([px - 8, yy - 8, px + pw + 8, yy + ph + 8], fill="#000000")
        img.paste(tile, (px, yy))
        d = ImageDraw.Draw(img)
        if pn.get("label"):
            draw_label(img, pn["label"], (px + pw / 2) / W, (yy + ph * .55) / H, t - .12 * i, size=46)
    return img


def finish(img, C, si, fi, t, dur, sc):
    """Brightness flicker / fade-in, vignette, film grain, scare glitch."""
    f = 1.0
    fl = sc.get("flicker", .35)
    n = math.sin(t * 47 + si * 3) * math.sin(t * 13.1)
    if fl and n > .82:
        f -= fl * .6
    f -= fl * .05 * math.sin(t * 9)
    if si > 0:
        f *= min(1.0, t / .22)
    if f < .995:
        img = ImageEnhance.Brightness(img).enhance(max(.05, f))
    img = ImageChops.multiply(img, vignette())
    img = ImageChops.add(img, grain(fi), 1.0, -128)
    if sc.get("scare") and t < .30:
        img = glitch(img, fi, 1.0 - t / .30)
        img = Image.blend(img, Image.new("RGB", (W, H), (150, 0, 0)), .35 * (1 - t / .30))
    elif sc.get("glitch") and t < .25:
        img = glitch(img, fi, .6)
    return img


def compose(si, fi):
    C = _CTX
    sc, info = C["scenes"][si], C["infos"][si]
    t, dur = fi / FPS, info["dur"]
    knocks = sc.get("knocks") or ([.3, .95, 1.6] if "knock" in (sc.get("sfx") or []) else [])
    if sc.get("collage"):
        img = compose_collage(C, si, t, dur)
    else:
        art, meta = scene_art(C, si)
        box, z = camera_box(sc, t, dur, meta, knocks)
        img = art.resize((W, H), Image.BILINEAR, box=box)
        if sc.get("fog", True):
            off = int(t * 22 + si * 97) % W
            img.paste(Image.new("RGB", (W, H), (150, 172, 170)), (0, 0), fog_mask().crop((off, 0, off + W, H)))
        sx, sy = W / (box[2] - box[0]), H / (box[3] - box[1])
        if meta.get("eyes") and sc.get("eyes_glow", True):
            blink = (t % 4.2) > 4.08
            k = 0 if blink else .55 + .45 * math.sin(t * 3.1)
            for ex, ey in meta["eyes"]:
                add_glow(img, (ex - box[0]) * sx, (ey - box[1]) * sy, 95 * sx, (255, 25, 25), k)
        if meta.get("ripple"):
            rx, ry = (meta["ripple"][0] - box[0]) * sx, (meta["ripple"][1] - box[1]) * sy
            d = ImageDraw.Draw(img)
            for tk in knocks:
                age = t - tk
                if 0 <= age < .8:
                    r = 40 + age * 700
                    fade = 1 - age / .8
                    d.ellipse([rx - r, ry - r, rx + r, ry + r], outline=(int(225 * fade), int(20 * fade), int(20 * fade)), width=8)
    img = finish(img, C, si, fi, t, dur, sc)
    if sc.get("tag"):
        draw_tag(img, sc["tag"])
    if sc.get("label") and not sc.get("collage"):
        lx, ly = sc.get("label_xy", (.5, .56))
        draw_label(img, sc["label"], lx, ly, t)
    if sc.get("arrow"):
        ax, ay, aa = sc["arrow"]
        draw_arrow(img, ax * W, ay * H, aa, t)
    if sc.get("title"):
        draw_title(img, sc["title"], sc.get("title_y", .17), t, size=sc.get("title_size", 170), jitter=1.0 if sc.get("scare") else 0.0)
    MR.draw_caption(ImageDraw.Draw(img), info["words"], t, C["font"], 100, False, True, si, y=1580, color="#FF2A2A")
    return img


def render_job(si):
    C = _CTX
    out = C["work"] / f"seg{si:02d}.mp4"
    if out.exists():
        return si
    part = C["work"] / f"seg{si:02d}.part.mp4"
    a, b = C["bounds"][si], C["bounds"][si + 1]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-maxrate", "5M", "-bufsize", "10M", "-pix_fmt", "yuv420p", str(part)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(b - a):
        ff.stdin.write(compose(si, fi).tobytes())
    ff.stdin.close()
    ff.wait()
    os.replace(part, out)
    return si


# ───────────────────────── dark audio ─────────────────────────
def synth_dark(dur):
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR
    rng = np.random.default_rng(11)
    drone = (.55 * np.sin(2 * np.pi * 55 * t + 1.2 * np.sin(2 * np.pi * .05 * t)) + .35 * np.sin(2 * np.pi * 58.3 * t)
             + .22 * np.sin(2 * np.pi * 82.4 * t + .6 * np.sin(2 * np.pi * .09 * t)))
    drone *= (.6 + .4 * np.sin(2 * np.pi * t / 14.0)) * .33
    hi = np.sin(2 * np.pi * np.cumsum(880 + 60 * np.sin(2 * np.pi * t / 9.0)) / SR) * .022 * (.5 + .5 * np.sin(2 * np.pi * t / 6.5)) ** 2
    wn = rng.normal(size=n)
    c = np.cumsum(wn)
    wind = np.zeros(n)
    wind[300:-300] = (c[600:] - c[:-600]) / 600
    wind = wind / (np.abs(wind).max() + 1e-9) * .22 * (.5 + .5 * np.sin(2 * np.pi * t / 11 + 1))
    out = (drone + hi + wind).astype(np.float32)
    th = np.arange(int(.25 * SR)) / SR
    thump = (np.sin(2 * np.pi * 48 * th) * np.exp(-th * 18)).astype(np.float32)
    bt = 0.4
    while bt < dur:
        MR.add(out, thump * .55, bt)
        MR.add(out, thump * .34, bt + .26)
        bt += 1.15 - .45 * (bt / dur)
    return out


def sfx_knock():
    t = np.arange(int(.4 * SR)) / SR
    rng = np.random.default_rng(3)
    return (np.sin(2 * np.pi * (150 - 70 * t / .4) * t) * np.exp(-t * 26) + rng.normal(size=len(t)) * np.exp(-t * 170) * .6).astype(np.float32)


def sfx_sting():
    t = np.arange(int(1.3 * SR)) / SR
    rng = np.random.default_rng(4)
    ch = sum(np.sin(2 * np.pi * f * t * (1 - .12 * t)) for f in (233.1, 246.9, 349.2, 466.2, 659.3))
    return ((ch * .22 + rng.normal(size=len(t)) * .5 * np.exp(-t * 14)) * np.exp(-t * 2.6)).astype(np.float32)


def sfx_whisper():
    t = np.arange(int(1.6 * SR)) / SR
    rng = np.random.default_rng(6)
    x = np.diff(rng.normal(size=len(t) + 1))
    x -= np.convolve(x, np.ones(12) / 12, "same")
    return (x * np.sin(np.pi * t / 1.6) ** 2 * .9).astype(np.float32)


def sfx_creak():
    t = np.arange(int(1.5 * SR)) / SR
    f = 110 + 120 * (t / 1.5) ** 1.5 + 12 * np.sin(2 * np.pi * 7 * t)
    ph = np.cumsum(f) / SR
    saw = 2 * (ph % 1) - 1
    return (saw * np.sin(np.pi * t / 1.5) ** 1.5 * .45).astype(np.float32)


SFX = {"knock": sfx_knock, "sting": sfx_sting, "whisper": sfx_whisper, "creak": sfx_creak, "boom": lambda: MR.sfx_boom()}


def build_mix(wavs, infos, work, scenes, no_music, no_sfx, music=None):
    voice = np.concatenate([MR.read_wav(w) for w in wavs])
    total = len(voice) / SR
    mix = voice.copy()
    if not no_music:
        if music:
            mw = Path(work) / "m.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", music, "-ar", str(SR), "-ac", "1", str(mw)], check=True)
            m = MR.read_wav(mw)
            m = np.tile(m, int(len(voice) / max(1, len(m))) + 1)[:len(voice)]
        else:
            m = synth_dark(total + .5)[:len(voice)]
        m = m / (np.abs(m).max() + 1e-9) * .5
        e = np.abs(voice)
        c = np.cumsum(e)
        w = int(.12 * SR)
        sm = np.zeros(len(e))
        sm[w // 2:-w // 2] = (c[w:] - c[:-w]) / w
        duck = 1 - .5 * np.clip(sm / (np.percentile(sm, 95) + 1e-9), 0, 1)
        mix += m * duck
    if not no_sfx:
        wh = MR.sfx_whoosh()
        cache = {}
        st = 0.0
        for i, (sc, inf) in enumerate(zip(scenes, infos)):
            if i > 0:
                MR.add(mix, wh * .14, st - .05)
            for item in (sc.get("sfx") or []):
                name, off = (item if isinstance(item, (list, tuple)) else (item, None))
                snd = cache.setdefault(name, SFX[name]())
                if name == "knock":
                    for tk in (sc.get("knocks") or [.3, .95, 1.6]):
                        MR.add(mix, snd * .9, st + tk)
                else:
                    MR.add(mix, snd * {"sting": .75, "whisper": .55, "creak": .5, "boom": .6}.get(name, .6), st + (off if off is not None else .1))
            st += inf["dur"]
    mix /= max(1.0, np.abs(mix).max() / .95)
    out = Path(work) / "mix.wav"
    MR.write_wav(out, mix)
    return out


# ───────────────────────── main entry ─────────────────────────
def run(a, spec):
    import importlib.util
    scenes = spec["scenes"]
    engine = "none" if a.no_tts else a.engine
    if engine == "auto":
        engine = "kokoro" if importlib.util.find_spec("kokoro_onnx") else "edge"
    print("› voice engine:", engine, flush=True)
    speed = spec.get("speed", .90) if a.speed == 1.06 else a.speed
    MR.OPTS.update(speed=speed, el_model=a.el_model)
    defaults = {"kokoro": "am_onyx", "edge": "en-US-GuyNeural", "elevenlabs": os.environ.get("ELEVENLABS_VOICE_ID", MR.EL_DEFAULT_VOICE)}
    default_voice = a.voice or spec.get("voice_" + engine) or defaults.get(engine, "")
    voices = {} if a.voice else dict(spec.get("voices", {}))
    font = MR.font_path("anton", a.font)
    key = hashlib.md5((json.dumps(spec, sort_keys=True) + f"{engine}{a.voice}{speed}{a.rate}{a.music}{a.no_music}{a.no_sfx}{a.images}{a.imagegen}L1").encode()).hexdigest()[:10]
    work = Path(a.work) if a.work else HERE / ".work" / key
    work.mkdir(parents=True, exist_ok=True)
    print("› audio…", flush=True)
    infos, wavs = MR.make_voice(scenes, voices, default_voice, a.rate, work / "audio", engine, spec.get("lang", "en"))
    audio = build_mix(wavs, infos, work, scenes, a.no_music, a.no_sfx, a.music)
    cum, bounds = 0.0, [0]
    for inf in infos:
        cum += inf["dur"]
        bounds.append(int(round(cum * FPS)))
    _CTX.update(scenes=scenes, spec=spec, infos=infos, font=font, work=work, bounds=bounds,
                images_dir=a.images, imagegen=a.imagegen)
    n = len(scenes)
    if a.imagegen and not a.images:
        prefetch_images(scenes, spec)
    todo = [i for i in range(n) if not (work / f"seg{i:02d}.mp4").exists()]
    print(f"› video: {n - len(todo)}/{n} scenes cached, rendering {len(todo)} ({bounds[-1] / FPS:.1f}s total)", flush=True)
    t0 = time.time()
    jobs = a.jobs or os.cpu_count() or 1
    if jobs > 1 and len(todo) > 1 and not a.budget:
        with mp.Pool(jobs) as pool:
            for si in pool.imap_unordered(render_job, todo):
                print(f"  scene {si + 1}/{n} ✓", flush=True)
    else:
        for si in todo:
            if a.budget and time.time() - t0 > a.budget:
                break
            render_job(si)
            print(f"  scene {si + 1}/{n} ✓  ({time.time() - t0:.0f}s)", flush=True)
    if [i for i in range(n) if not (work / f"seg{i:02d}.mp4").exists()]:
        print("⏸ time budget reached — run the same command again to continue.")
        sys.exit(3)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{(work / f'seg{i:02d}.mp4').resolve()}'\n" for i in range(n)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
                    "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", a.out], check=True)
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("✔ saved:", a.out)


def write_prompts(spec, out):
    style = spec.get("image_style", IMG_STYLE)
    lines = []
    for i, sc in enumerate(spec["scenes"]):
        if sc.get("image_prompt"):
            lines.append(f"{i + 1:02d}: {sc['image_prompt']}. {style}")
    Path(out).write_text("\n\n".join(lines), encoding="utf-8")
    print(f"✔ {len(lines)} image prompts written to {out}  (save the images as 01.png, 02.png … in a folder, then use --images DIR)")
