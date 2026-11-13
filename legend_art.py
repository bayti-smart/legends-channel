"""
Procedural dark-comic horror art (school, corridor, bathroom, stall, eyes, girl, forest).
Everything is drawn in unit coordinates (0..1) on a CW x CH canvas, so it is resolution independent.
These are placeholders you can replace with real AI-generated illustrations (see README / --images).
"""
import math, random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

CW, CH = 1350, 2400          # art canvas = 1.25 x the 1080x1920 frame, leaves room for camera moves


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def grad(top, bottom, size=(CW, CH)):
    mask = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, rgb(bottom)), Image.new("RGB", size, rgb(top)), mask)


def poly(d, pts, fill, ow=6, outline="#000000"):
    d.polygon(pts, fill=fill)
    if ow:
        d.line(list(pts) + [pts[0]], fill=outline, width=ow, joint="curve")


def glow(img, cx, cy, r, color, strength=0.8, blur=None):
    """Additive blurred glow."""
    pad = int(r * 3)
    x0, y0 = int(cx - pad), int(cy - pad)
    patch = Image.new("RGB", (pad * 2, pad * 2), (0, 0, 0))
    ImageDraw.Draw(patch).ellipse([pad - r, pad - r, pad + r, pad + r], fill=color)
    patch = patch.filter(ImageFilter.GaussianBlur(blur or r * 0.6)).point(lambda v: int(v * strength))
    base = img.crop((x0, y0, x0 + pad * 2, y0 + pad * 2))
    img.paste(ImageChops.add(base, patch), (x0, y0))
    return img


def fog(img, y0, y1, alpha, seed, color=(150, 172, 170), n=14):
    rnd = random.Random(seed)
    layer = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rnd.uniform(-.2, 1.1) * CW, rnd.uniform(y0, y1) * CH
        rw, rh = rnd.uniform(.25, .6) * CW, rnd.uniform(.015, .04) * CH
        d.ellipse([x - rw, y - rh, x + rw, y + rh], fill=int(255 * alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(45))
    img.paste(Image.new("RGB", img.size, color), (0, 0), layer)


def hatch(img, step=18, alpha=34):
    """Comic-style diagonal hatching over the whole image."""
    layer = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(layer)
    for k in range(-CH, CW, step):
        d.line([(k, 0), (k + CH * 0.55, CH)], fill=alpha, width=2)
    img.paste(Image.new("RGB", img.size, (0, 0, 0)), (0, 0), layer)


def tree(d, x, y, ang, length, width, depth, rnd, col="#030606"):
    if depth == 0 or length < 10:
        return
    x2, y2 = x + math.sin(ang) * length, y - math.cos(ang) * length
    d.line([x, y, x2, y2], fill=col, width=max(2, int(width)))
    for da in (-0.52, 0.46):
        tree(d, x2, y2, ang + da + rnd.uniform(-.22, .22), length * rnd.uniform(.66, .8), width * .68, depth - 1, rnd, col)


def girl_silhouette(d, cx, top, h, col="#020404", eyes=True, tilt=0.0):
    """Backlit silhouette: bob haircut, blouse, skirt, hanging arms. h = total height in px."""
    hr = h * 0.085
    hy = top + hr * 1.3
    # legs
    for sx in (-1, 1):
        d.rectangle([cx + sx * h * .035 - h * .022, top + h * .66, cx + sx * h * .035 + h * .022, top + h], fill=col)
    # skirt + blouse
    d.polygon([(cx - h * .10, top + h * .45), (cx + h * .10, top + h * .45), (cx + h * .15, top + h * .68), (cx - h * .15, top + h * .68)], fill=col)
    d.polygon([(cx - h * .095, top + h * .22), (cx + h * .095, top + h * .22), (cx + h * .085, top + h * .46), (cx - h * .085, top + h * .46)], fill=col)
    # arms (slightly forward, limp)
    for sx in (-1, 1):
        d.line([(cx + sx * h * .09, top + h * .25), (cx + sx * h * .13, top + h * .45), (cx + sx * h * .12, top + h * .60)], fill=col, width=int(h * .035), joint="curve")
    # neck, head, bob hair with straight bangs
    d.rectangle([cx - hr * .28, hy + hr * .7, cx + hr * .28, top + h * .24], fill=col)
    d.ellipse([cx - hr, hy - hr, cx + hr, hy + hr], fill=col)
    bob = [(cx - hr * 1.28, hy - hr * .2), (cx - hr * 1.05, hy - hr * 1.2), (cx, hy - hr * 1.38), (cx + hr * 1.05, hy - hr * 1.2),
           (cx + hr * 1.28, hy - hr * .2), (cx + hr * 1.2, hy + hr * 1.05), (cx + hr * .95, hy + hr * 1.05), (cx + hr * .9, hy - hr * .25),
           (cx - hr * .9, hy - hr * .25), (cx - hr * .95, hy + hr * 1.05), (cx - hr * 1.2, hy + hr * 1.05)]
    d.polygon(bob, fill=col)
    return hy, hr


# ───────────────────────── scenes ─────────────────────────
def art_school(seed=1):
    rnd = random.Random(seed)
    img = grad("#050E0E", "#223E3D")
    mx, my, mr = .74 * CW, .15 * CH, .085 * CW
    glow(img, mx, my, mr * 1.5, (80, 105, 95), .9, blur=mr)
    d = ImageDraw.Draw(img)
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill="#DCE6D6", outline="#000000", width=5)
    for cx, cy, cr in ((-.3, -.2, .22), (.25, .15, .3), (-.1, .45, .16)):
        d.ellipse([mx + cx * mr - cr * mr, my + cy * mr - cr * mr, mx + cx * mr + cr * mr, my + cy * mr + cr * mr], fill="#B9C6B4")
    for _ in range(7):   # dark cloud streaks
        x, y = rnd.uniform(0, 1) * CW, rnd.uniform(.05, .38) * CH
        d.ellipse([x - 260, y - 22, x + 260, y + 22], fill="#0A1717")
    by0, by1 = .50 * CH, .80 * CH
    d.rectangle([-30, by0, CW + 30, by1], fill="#0A1213", outline="#000000", width=7)
    d.rectangle([-30, by0 - 26, CW + 30, by0], fill="#050A0B")
    poly(d, [(.36 * CW, by0), (.36 * CW, .42 * CH), (.5 * CW, .395 * CH), (.64 * CW, .42 * CH), (.64 * CW, by0)], "#0B1415")
    d.ellipse([.455 * CW, .425 * CH, .545 * CW, .425 * CH + .09 * CW], fill="#C9D3BE", outline="#000000", width=5)
    d.line([.5 * CW, .43 * CH, .5 * CW, .45 * CH], fill="#000000", width=5)
    d.line([.5 * CW, .45 * CH, .52 * CW, .452 * CH], fill="#000000", width=5)
    lit_red = None
    for r in range(3):
        for c in range(10):
            wx, wy = .035 * CW + c * .095 * CW, by0 + .035 * CH + r * .085 * CH
            w, h = .06 * CW, .055 * CH
            col = "#14282B"
            if rnd.random() < .10:
                col = "#8E7A3C"
            if r == 0 and c == 7:    # third floor: the bathroom window
                col, lit_red = "#E01B1B", (wx + w / 2, wy + h / 2)
            d.rectangle([wx, wy, wx + w, wy + h], fill=col, outline="#000000", width=4)
            d.line([wx + w / 2, wy, wx + w / 2, wy + h], fill="#000000", width=3)
    if lit_red:
        glow(img, lit_red[0], lit_red[1], 70, (225, 20, 20), .95, blur=60)
        d = ImageDraw.Draw(img)
    d.rectangle([0, by1, CW, CH], fill="#040808")
    d.rectangle([.44 * CW, by1 - .06 * CH, .56 * CW, by1], fill="#050B0B", outline="#000000", width=5)   # entrance
    tree(d, .13 * CW, .93 * CH, -.12, 360, 34, 7, rnd)
    for i in range(0, 34):   # fence
        x = i * CW / 33
        d.polygon([(x - 9, .87 * CH), (x, .85 * CH), (x + 9, .87 * CH), (x + 9, CH), (x - 9, CH)], fill="#020505")
    d.rectangle([0, .90 * CH, CW, .905 * CH], fill="#020505")
    fog(img, .70, .86, .38, seed)
    hatch(img)
    return img, {"hot": lit_red}


def art_corridor(seed=2, figure=False):
    vx, vy = .5 * CW, .47 * CH
    img = Image.new("RGB", (CW, CH), "#040A0B")
    d = ImageDraw.Draw(img)

    def sec(s):
        return dict(l=vx - .62 * CW * s, r=vx + .62 * CW * s, t=vy - .40 * CH * s, b=vy + .40 * CH * s)

    sc = [1.2, .85, .6, .42, .30, .21, .15, .105, .075, .05]
    lights = Image.new("RGB", (CW, CH), (0, 0, 0))
    ld = ImageDraw.Draw(lights)
    for i, (a, b) in enumerate(zip(sc[:-1], sc[1:])):
        A, B = sec(a), sec(b)
        poly(d, [(A['l'], A['b']), (A['r'], A['b']), (B['r'], B['b']), (B['l'], B['b'])], "#172A2B" if i % 2 else "#122224", 3)
        poly(d, [(A['l'], A['t']), (A['r'], A['t']), (B['r'], B['t']), (B['l'], B['t'])], "#0A1315", 3)
        poly(d, [(A['l'], A['t']), (B['l'], B['t']), (B['l'], B['b']), (A['l'], A['b'])], "#12292C", 3)
        poly(d, [(A['r'], A['t']), (B['r'], B['t']), (B['r'], B['b']), (A['r'], A['b'])], "#10262A", 3)
        s1, s2 = a + (b - a) * .18, a + (b - a) * .82
        for side in (-1, 1):
            def xw(s): return vx + side * .62 * CW * s
            def fl(s): return vy + .40 * CH * s
            def tp(s): return fl(s) - .64 * (.8 * CH * s)
            if (i + (side > 0)) % 2 == 0:
                poly(d, [(xw(s1), tp(s1)), (xw(s2), tp(s2)), (xw(s2), fl(s2)), (xw(s1), fl(s1))], "#0A1819", 5)
                wy1, wy2 = tp(s1) + .1 * (fl(s1) - tp(s1)), tp(s2) + .1 * (fl(s2) - tp(s2))
                poly(d, [(xw(s1 + (s2 - s1) * .25), wy1 + .06 * (fl(s1) - tp(s1))), (xw(s2 - (s2 - s1) * .25), wy2 + .06 * (fl(s2) - tp(s2))),
                         (xw(s2 - (s2 - s1) * .25), wy2 + .28 * (fl(s2) - tp(s2))), (xw(s1 + (s2 - s1) * .25), wy1 + .28 * (fl(s1) - tp(s1)))], "#050D0E", 3)
        if i % 2 == 0:
            ya, yb = A['t'] + (B['t'] - A['t']) * .25, A['t'] + (B['t'] - A['t']) * .6
            sa, sb = a + (b - a) * .25, a + (b - a) * .6
            ld.polygon([(vx - .10 * CW * sa, ya), (vx + .10 * CW * sa, ya), (vx + .10 * CW * sb, yb), (vx - .10 * CW * sb, yb)], fill=(190, 215, 200))
    E = sec(sc[-1])
    d.rectangle([E['l'], E['t'], E['r'], E['b']], fill="#010303")
    d.rectangle([vx - 22, E['t'] - 10, vx + 22, E['t'] + 12], fill="#E01B1B")
    lights = lights.filter(ImageFilter.GaussianBlur(26))
    img = ImageChops.add(img, lights.point(lambda v: int(v * .55)))
    glow(img, vx, E['t'], 40, (225, 20, 20), .9, blur=40)
    d = ImageDraw.Draw(img)
    if figure:
        girl_silhouette(d, vx, vy - .02 * CH, .095 * CH, col="#010202")
    fog(img, .62, .80, .30, seed)
    hatch(img, alpha=30)
    return img, {"hot": (vx, E['t'])}


def art_bathroom(seed=3, eyes=True):
    img = Image.new("RGB", (CW, CH), "#0B1718")
    d = ImageDraw.Draw(img)
    d.rectangle([0, .12 * CH, CW, .74 * CH], fill="#1B2F31")
    for x in range(0, CW, 66):
        d.line([x, .12 * CH, x, .74 * CH], fill="#233B3D", width=2)
    for y in range(int(.12 * CH), int(.74 * CH), 84):
        d.line([0, y, CW, y], fill="#233B3D", width=2)
    d.rectangle([0, 0, CW, .12 * CH], fill="#050B0C")
    vx = CW / 2
    d.polygon([(0, .74 * CH), (CW, .74 * CH), (CW, CH), (0, CH)], fill="#142628")
    for k in range(-6, 14):
        xt = k * CW / 8
        d.line([(xt, .74 * CH), (vx + (xt - vx) * 2.6, CH)], fill="#1D3335", width=3)
    for y in (.775, .82, .88, .96):
        d.line([0, y * CH, CW, y * CH], fill="#1D3335", width=3)
    eye_pos = []
    for i in range(4):
        x0 = (.045 + .225 * i) * CW
        x1 = x0 + .205 * CW
        yt, yb = .26 * CH, .72 * CH
        d.rectangle([x0 - .012 * CW, .22 * CH, x1 + .012 * CW, .745 * CH], fill="#050C0D")           # partition frame
        d.rectangle([x0, yt, x1, .745 * CH], fill="#010303")                                          # opening
        if i == 2:   # the third stall: door slightly ajar, darkness and eyes inside
            poly(d, [(x0, yt - 8), (x0 + .05 * CW, yt + 6), (x0 + .05 * CW, yb - 6), (x0, yb + 8)], "#2D5C55", 6)
            if eyes:
                ex, ey = (x0 + x1) / 2 + .02 * CW, .47 * CH
                eye_pos = [(ex - 34, ey), (ex + 34, ey)]
        else:
            poly(d, [(x0, yt), (x1, yt), (x1, yb), (x0, yb)], "#2D5C55", 7)
            for k in range(1, 4):
                d.line([x0 + 10, yt + k * (yb - yt) / 4, x1 - 10, yt + k * (yb - yt) / 4], fill="#1F433E", width=6)
            d.rectangle([x1 - .035 * CW, (yt + yb) / 2 - 8, x1 - .015 * CW, (yt + yb) / 2 + 8], fill="#C9D3BE", outline="#000000", width=3)
            d.ellipse([x0 + .09 * CW - 9, yt + 30, x0 + .09 * CW + 9, yt + 48], fill="#E01B1B" if i == 3 else "#2E9B5B", outline="#000000", width=3)
        d.rectangle([x0, yb, x1, .745 * CH], fill="#010303")                                          # gap under doors
    d.rectangle([vx - .22 * CW, .015 * CH, vx + .22 * CW, .035 * CH], fill="#D9E8D0", outline="#000000", width=4)
    lamp = Image.new("RGB", (CW, CH), (0, 0, 0))
    ImageDraw.Draw(lamp).polygon([(vx - .2 * CW, .035 * CH), (vx + .2 * CW, .035 * CH), (vx + .55 * CW, .74 * CH), (vx - .55 * CW, .74 * CH)], fill=(60, 85, 78))
    img = ImageChops.add(img, lamp.filter(ImageFilter.GaussianBlur(60)))
    for ex, ey in eye_pos:
        glow(img, ex, ey, 36, (225, 20, 20), .9, blur=34)
    d = ImageDraw.Draw(img)
    for ex, ey in eye_pos:
        d.ellipse([ex - 20, ey - 11, ex + 20, ey + 11], fill="#FF2A2A", outline="#000000", width=3)
        d.ellipse([ex - 5, ey - 11, ex + 5, ey + 11], fill="#000000")
    fog(img, .68, .80, .30, seed)
    hatch(img)
    return img, {"eyes": eye_pos, "hot": eye_pos[0] if eye_pos else None}


def art_stall(seed=4, feet=True):
    img = Image.new("RGB", (CW, CH), "#040A0B")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, .10 * CW, CH], fill="#0B1718")
    d.rectangle([.90 * CW, 0, CW, CH], fill="#0B1718")
    poly(d, [(.10 * CW, .05 * CH), (.90 * CW, .05 * CH), (.90 * CW, .90 * CH), (.10 * CW, .90 * CH)], "#2A5750", 10)
    for k in range(1, 6):
        y = .05 * CH + k * .85 * CH / 6
        d.rectangle([.12 * CW, y - 10, .88 * CW, y + 10], fill="#1D423C")
    rnd = random.Random(seed)
    for _ in range(26):
        x, y = rnd.uniform(.14, .86) * CW, rnd.uniform(.08, .88) * CH
        d.line([x, y, x + rnd.uniform(-60, 60), y + rnd.uniform(-90, 90)], fill="#5E8F86", width=2)
    d.rectangle([.44 * CW, .17 * CH, .56 * CW, .21 * CH], fill="#C9D3BE", outline="#000000", width=5)       # lock
    d.ellipse([.485 * CW, .178 * CH, .515 * CW, .178 * CH + .03 * CW], fill="#E01B1B", outline="#000000", width=4)
    d.ellipse([.43 * CW, .40 * CH, .57 * CW, .50 * CH], outline="#1B3F39", width=6)                           # dent where the knocks land
    d.rectangle([.10 * CW, .90 * CH, .90 * CW, CH], fill="#010202")
    if feet:   # small pale shoes in the gap
        for x in (.43, .55):
            d.ellipse([x * CW - 48, .925 * CH, x * CW + 48, .925 * CH + 48], fill="#2B3B3C", outline="#000000", width=4)
            d.rectangle([x * CW - 28, .905 * CH, x * CW + 28, .93 * CH], fill="#3A4D4E")
    lamp = Image.new("RGB", (CW, CH), (0, 0, 0))
    ImageDraw.Draw(lamp).ellipse([.1 * CW, .15 * CH, .9 * CW, .6 * CH], fill=(40, 62, 56))
    img = ImageChops.add(img, lamp.filter(ImageFilter.GaussianBlur(110)))
    fog(img, .80, .95, .28, seed)
    hatch(img, alpha=38)
    return img, {"ripple": (.5 * CW, .45 * CH)}


def art_eyes(seed=5):
    img = grad("#020506", "#061012")
    glow(img, .5 * CW, .46 * CH, 520, (24, 52, 54), .9, blur=380)
    d = ImageDraw.Draw(img)
    cx, cy = .5 * CW, .50 * CH
    d.polygon([(.08 * CW, CH), (.14 * CW, .78 * CH), (.30 * CW, .70 * CH), (.70 * CW, .70 * CH), (.86 * CW, .78 * CH), (.92 * CW, CH)], fill="#0A1517")   # shoulders / blouse
    d.polygon([(.44 * CW, .70 * CH), (.5 * CW, .76 * CH), (.56 * CW, .70 * CH)], fill="#16282B")
    d.rectangle([.44 * CW, .60 * CH, .56 * CW, .72 * CH], fill="#0C191B")
    d.ellipse([cx - .21 * CW, cy - .21 * CH * .62, cx + .21 * CW, cy + .30 * CH * .62], fill="#17292C", outline="#000000", width=6)     # face
    bob = [(cx - .30 * CW, cy + .10 * CH), (cx - .27 * CW, cy - .20 * CH), (cx, cy - .26 * CH), (cx + .27 * CW, cy - .20 * CH), (cx + .30 * CW, cy + .10 * CH),
           (cx + .25 * CW, cy + .17 * CH), (cx + .20 * CW, cy + .17 * CH), (cx + .20 * CW, cy - .06 * CH), (cx - .20 * CW, cy - .06 * CH),
           (cx - .20 * CW, cy + .17 * CH), (cx - .25 * CW, cy + .17 * CH)]
    poly(d, bob, "#030707", 6)
    ey = cy + .01 * CH
    eyes = [(cx - .075 * CW, ey), (cx + .075 * CW, ey)]
    for ex, e_y in eyes:
        glow(img, ex, e_y, 60, (225, 20, 20), .95, blur=60)
    d = ImageDraw.Draw(img)
    for ex, e_y in eyes:
        d.ellipse([ex - 38, e_y - 20, ex + 38, e_y + 20], fill="#FF2A2A", outline="#000000", width=4)
        d.ellipse([ex - 9, e_y - 20, ex + 9, e_y + 20], fill="#000000")
    fog(img, .78, .92, .22, seed)
    hatch(img, alpha=40)
    return img, {"eyes": eyes, "hot": eyes[0]}


def art_girl(seed=6):
    img = Image.new("RGB", (CW, CH), "#030909")
    d = ImageDraw.Draw(img)
    gx0, gx1, gy0, gy1 = .20 * CW, .80 * CW, .10 * CH, .86 * CH
    inner = grad("#8DB5B0", "#2C4B49", (int(gx1 - gx0), int(gy1 - gy0)))
    img.paste(inner, (int(gx0), int(gy0)))
    d = ImageDraw.Draw(img)
    for x in range(int(gx0), int(gx1), 70):
        d.line([x, gy0, x, gy1], fill="#6E918D", width=2)
    d.rectangle([gx0, gy0, gx1, gy1], outline="#000000", width=14)
    d.polygon([(gx0, gy1), (gx1, gy1), (gx1 + .1 * CW, CH), (gx0 - .1 * CW, CH)], fill="#0A1516")
    hy, hr = girl_silhouette(d, .5 * CW, .20 * CH, .66 * CH, col="#010303")
    lay = Image.new("RGB", (CW, CH), (0, 0, 0))
    glow(img, .5 * CW - hr * .38, hy + hr * .05, 14, (225, 20, 20), .9, blur=16)
    glow(img, .5 * CW + hr * .38, hy + hr * .05, 14, (225, 20, 20), .9, blur=16)
    d = ImageDraw.Draw(img)
    for sx in (-1, 1):
        ex = .5 * CW + sx * hr * .38
        d.ellipse([ex - 12, hy + hr * .05 - 7, ex + 12, hy + hr * .05 + 7], fill="#FF2A2A")
    fog(img, .80, .95, .35, seed)
    hatch(img)
    return img, {"eyes": [(.5 * CW - hr * .38, hy + hr * .05), (.5 * CW + hr * .38, hy + hr * .05)], "hot": (.5 * CW, hy)}


def art_forest(seed=7):
    rnd = random.Random(seed)
    img = grad("#08140E", "#26452F")
    glow(img, .5 * CW, .43 * CH, 260, (90, 135, 105), .65, blur=220)
    d = ImageDraw.Draw(img)

    def trunk(x, w, col, outline=0, bark=True):
        pts = [(x - w, CH), (x - w * .75, .55 * CH), (x - w * .6, -50), (x + w * .6, -50), (x + w * .75, .55 * CH), (x + w, CH)]
        poly(d, pts, col, outline)
        if bark:
            for _ in range(int(w / 5)):
                yy = rnd.uniform(.1, .9) * CH
                d.line([x + rnd.uniform(-w * .5, w * .5), yy, x + rnd.uniform(-w * .5, w * .5), yy + rnd.uniform(40, 200)], fill="#000000", width=2)

    for k in range(34):                                   # far trees (thin, hazy)
        x = rnd.uniform(0, 1) * CW
        if abs(x - CW / 2) > .09 * CW:
            trunk(x, rnd.uniform(8, 16), "#1B3526", bark=False)
    fog(img, .40, .72, .30, seed, color=(130, 175, 145), n=12)
    d = ImageDraw.Draw(img)
    for k in range(16):                                   # mid trees
        x = rnd.uniform(0, 1) * CW
        if abs(x - CW / 2) > .17 * CW:
            trunk(x, rnd.uniform(24, 40), "#0E2016", 5)
    d.polygon([(.47 * CW, .46 * CH), (.53 * CW, .46 * CH), (.86 * CW, CH), (.14 * CW, CH)], fill="#3B4B2B")       # the path
    d.polygon([(.485 * CW, .46 * CH), (.515 * CW, .46 * CH), (.60 * CW, CH), (.40 * CW, CH)], fill="#4A5B36")
    for k in range(7):                                                                                           # footprints
        t = k / 7
        y = (.56 + .38 * t) * CH
        for sx in (-1, 1):
            cx = CW * (.5 + sx * .03 * (1 + 2.4 * t))
            d.ellipse([cx - 16 * (1 + t), y - 24 * (1 + t), cx + 16 * (1 + t), y + 24 * (1 + t)], fill="#262F1B")
    fx, fy, fh = .5 * CW, .46 * CH, .12 * CH              # tall thin figure with antlers at the end of the path
    d.rectangle([fx - 9, fy - fh, fx + 9, fy], fill="#020403")
    d.ellipse([fx - 15, fy - fh - 22, fx + 15, fy - fh + 14], fill="#020403")
    for sx in (-1, 1):
        d.line([fx + sx * 8, fy - fh - 14, fx + sx * 40, fy - fh - 60, fx + sx * 34, fy - fh - 110], fill="#020403", width=5, joint="curve")
        d.line([fx + sx * 40, fy - fh - 60, fx + sx * 72, fy - fh - 80], fill="#020403", width=4)
        glow(img, fx + sx * 6, fy - fh - 2, 9, (225, 20, 20), 1.0, blur=10)
    d = ImageDraw.Draw(img)
    for x, w in ((.04, 70), (.13, 46), (.93, 80), (.99, 55)):   # framing trunks at the edges only
        trunk(x * CW, w, "#050C07", 6)
    fog(img, .82, .97, .26, seed + 1, color=(110, 150, 125), n=8)
    hatch(img)
    return img, {"hot": (fx, fy - fh)}


def masked_woman(d, cx, top, h, col="#010203"):
    """Long black hair, long coat, white surgical mask. h = total height in px."""
    hr = h * 0.075
    hy = top + hr * 1.4
    d.polygon([(cx - h * .12, top + h * .20), (cx + h * .12, top + h * .20), (cx + h * .17, top + h * .80), (cx - h * .17, top + h * .80)], fill=col)   # coat
    for sx in (-1, 1):
        d.rectangle([cx + sx * h * .05 - h * .02, top + h * .78, cx + sx * h * .05 + h * .02, top + h], fill=col)
        d.line([(cx + sx * h * .12, top + h * .24), (cx + sx * h * .15, top + h * .55)], fill=col, width=int(h * .03))
    d.ellipse([cx - hr, hy - hr, cx + hr, hy + hr], fill="#14201F")
    d.polygon([(cx - hr * 1.25, hy - hr * .6), (cx, hy - hr * 1.35), (cx + hr * 1.25, hy - hr * .6), (cx + hr * 1.45, hy + hr * 3.2),
               (cx + hr * .85, hy + hr * 3.0), (cx + hr * .8, hy - hr * .1), (cx - hr * .8, hy - hr * .1), (cx - hr * .85, hy + hr * 3.0),
               (cx - hr * 1.45, hy + hr * 3.2)], fill=col)
    d.rectangle([cx - hr * .78, hy + hr * .05, cx + hr * .78, hy + hr * .95], fill="#E8EFEA")
    return hy, hr


def art_street(seed=8, figure=False):
    rnd = random.Random(seed)
    vx, vy = .5 * CW, .47 * CH
    img = grad("#050A10", "#1A2B31")
    d = ImageDraw.Draw(img)
    for side in (-1, 1):                         # building silhouettes in two layers
        for layer, col, top0 in ((0, "#0B161B", .20), (1, "#050B0E", .12)):
            x = vx + side * (.12 + layer * .16) * CW
            for k in range(7):
                bw = rnd.uniform(.10, .2) * CW
                bh = rnd.uniform(top0, top0 + .28) * CH
                xa, xb = (x, x + side * bw) if side > 0 else (x + side * bw, x)
                d.rectangle([xa, vy - bh, xb, vy + .1 * CH], fill=col, outline="#000000", width=4)
                for wy in range(int(vy - bh + 40), int(vy + .05 * CH), 70):
                    for wx in range(int(xa + 18), int(xb - 30), 46):
                        if rnd.random() < .10:
                            d.rectangle([wx, wy, wx + 20, wy + 30], fill="#8E7A3C")
                x += side * bw * .92
    d.polygon([(vx - .02 * CW, vy), (vx + .02 * CW, vy), (CW * 1.25, CH), (-CW * .25, CH)], fill="#0B1418")    # wet road
    d.polygon([(vx - .02 * CW, vy), (vx - .1 * CW, vy), (-CW * .55, CH), (-CW * .25, CH)], fill="#16252A")       # sidewalks
    d.polygon([(vx + .02 * CW, vy), (vx + .1 * CW, vy), (CW * 1.55, CH), (CW * 1.25, CH)], fill="#16252A")
    for k in range(8):                                                                                           # lane dashes
        t = (k + 1) / 9
        y = vy + (CH - vy) * t ** 1.7
        w = 6 + 26 * t ** 1.7
        d.rectangle([vx - w / 2, y, vx + w / 2, y + 12 + 70 * t ** 1.7], fill="#3B4B4D")
    lamps = Image.new("RGB", (CW, CH), (0, 0, 0))
    ld = ImageDraw.Draw(lamps)
    spots = []
    for i, s_ in enumerate((1.0, .55, .3, .17)):
        side = -1 if i % 2 == 0 else 1
        gx, gy = vx + side * .5 * CW * s_, vy + .42 * CH * s_
        top = gy - .58 * CH * s_
        d.line([gx, gy, gx, top], fill="#020506", width=int(12 * s_ + 4))
        d.line([gx, top, gx - side * .09 * CW * s_, top], fill="#020506", width=int(10 * s_ + 3))
        lx = gx - side * .09 * CW * s_
        d.ellipse([lx - 26 * s_ - 6, top - 10 * s_ - 4, lx + 26 * s_ + 6, top + 12 * s_ + 4], fill="#E9E2B0")
        ld.ellipse([lx - 70 * s_, top - 50 * s_, lx + 70 * s_, top + 60 * s_], fill=(150, 140, 90))
        ld.polygon([(lx - 40 * s_, top + 10 * s_), (lx + 40 * s_, top + 10 * s_), (lx + 170 * s_, gy), (lx - 170 * s_, gy)], fill=(55, 52, 34))
        ld.ellipse([lx - 90 * s_, gy - 12 * s_, lx + 90 * s_, gy + 24 * s_], fill=(90, 84, 54))       # pool of light on the road
        spots.append((lx, top, gy))
    img = ImageChops.add(img, lamps.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img)
    hot = None
    if figure:
        fx, fy = vx + .015 * CW, vy + .075 * CH
        hy_, hr_ = masked_woman(d, fx, fy - .16 * CH, .17 * CH)
        hot = (fx, hy_)
        for sx in (-1, 1):
            glow(img, fx + sx * hr_ * .38, hy_ - hr_ * .25, 7, (225, 20, 20), 1.0, blur=8)
        d = ImageDraw.Draw(img)
    fog(img, .55, .85, .34, seed)
    hatch(img)
    return img, {"hot": hot or (vx, vy)}


def art_mask(seed=9):
    img = grad("#03080A", "#0A1618")
    glow(img, .5 * CW, .44 * CH, 560, (26, 54, 56), .9, blur=400)
    d = ImageDraw.Draw(img)
    cx, cy = .5 * CW, .46 * CH
    d.polygon([(.06 * CW, CH), (.12 * CW, .80 * CH), (.32 * CW, .70 * CH), (.68 * CW, .70 * CH), (.88 * CW, .80 * CH), (.94 * CW, CH)], fill="#091214")   # coat
    d.polygon([(.36 * CW, .70 * CH), (.5 * CW, .86 * CH), (.64 * CW, .70 * CH), (.58 * CW, .68 * CH), (.5 * CW, .75 * CH), (.42 * CW, .68 * CH)], fill="#050B0C", outline="#000000")
    hair = [(cx - .34 * CW, CH * .98), (cx - .30 * CW, cy - .06 * CH), (cx - .22 * CW, cy - .24 * CH), (cx, cy - .29 * CH), (cx + .22 * CW, cy - .24 * CH),
            (cx + .30 * CW, cy - .06 * CH), (cx + .34 * CW, CH * .98), (cx + .24 * CW, CH * .98), (cx + .20 * CW, cy + .02 * CH),
            (cx - .20 * CW, cy + .02 * CH), (cx - .24 * CW, CH * .98)]
    poly(d, hair, "#020405", 6)
    d.ellipse([cx - .20 * CW, cy - .17 * CH, cx + .20 * CW, cy + .17 * CH], fill="#22393B", outline="#000000", width=6)                                    # face
    d.polygon([(cx - .20 * CW, cy + .01 * CH), (cx + .20 * CW, cy + .01 * CH), (cx + .17 * CW, cy + .13 * CH), (cx, cy + .185 * CH), (cx - .17 * CW, cy + .13 * CH)],
              fill="#E6EDE8", outline="#000000", width=6)                                                                                              # mask
    for k in range(1, 4):
        yy = cy + .01 * CH + k * .035 * CH
        d.line([cx - .19 * CW + k * 6, yy, cx + .19 * CW - k * 6, yy], fill="#BFC9C4", width=4)
    d.line([cx - .20 * CW, cy + .02 * CH, cx - .26 * CW, cy - .02 * CH], fill="#BFC9C4", width=4)
    d.line([cx + .20 * CW, cy + .02 * CH, cx + .26 * CW, cy - .02 * CH], fill="#BFC9C4", width=4)
    d.line([cx - .12 * CW, cy - .075 * CH, cx - .03 * CW, cy - .062 * CH], fill="#000000", width=9)                                                         # brows
    d.line([cx + .12 * CW, cy - .075 * CH, cx + .03 * CW, cy - .062 * CH], fill="#000000", width=9)
    eyes = [(cx - .075 * CW, cy - .03 * CH), (cx + .075 * CW, cy - .03 * CH)]
    for ex, ey in eyes:
        glow(img, ex, ey, 56, (225, 20, 20), .9, blur=56)
    d = ImageDraw.Draw(img)
    for ex, ey in eyes:
        d.ellipse([ex - 34, ey - 15, ex + 34, ey + 15], fill="#FF2A2A", outline="#000000", width=4)
        d.ellipse([ex - 8, ey - 15, ex + 8, ey + 15], fill="#000000")
    fog(img, .80, .95, .22, seed)
    hatch(img, alpha=40)
    return img, {"eyes": eyes, "hot": eyes[0]}


def art_snow(seed=10):
    rnd = random.Random(seed)
    img = grad("#070D1B", "#2A3D5C")
    glow(img, .30 * CW, .16 * CH, 150, (90, 110, 150), .8, blur=140)
    d = ImageDraw.Draw(img)
    mx, my, mr = .30 * CW, .16 * CH, .075 * CW
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill="#E4ECF5", outline="#000000", width=5)
    d.polygon([(0, .60 * CH), (.3 * CW, .52 * CH), (.65 * CW, .58 * CH), (CW, .50 * CH), (CW, CH), (0, CH)], fill="#C9D6E6", outline="#000000")
    d.polygon([(0, .70 * CH), (.4 * CW, .64 * CH), (.8 * CW, .69 * CH), (CW, .65 * CH), (CW, CH), (0, CH)], fill="#E1EAF4", outline="#000000")
    for k in range(26):                                   # snowy pines
        x = rnd.uniform(-.05, 1.05) * CW
        y = rnd.uniform(.56, .74) * CH
        h = rnd.uniform(.08, .17) * CH
        w = h * .45
        for t in range(3):
            yy = y - h + t * h * .35
            d.polygon([(x, yy), (x - w * (.5 + t * .25), yy + h * .42), (x + w * (.5 + t * .25), yy + h * .42)], fill="#0B1620", outline="#000000")
            d.polygon([(x, yy), (x - w * (.3 + t * .15), yy + h * .22), (x + w * (.3 + t * .15), yy + h * .22)], fill="#DCE6F2")
    fx, fy, fh = .62 * CW, .67 * CH, .30 * CH           # the pale woman in a white kimono, long black hair
    hy, hr = fy - fh * .86, fh * .055
    d.polygon([(fx - fh * .10, fy - fh * .78), (fx + fh * .10, fy - fh * .78), (fx + fh * .22, fy), (fx - fh * .22, fy)], fill="#E9F0F7", outline="#000000")
    d.polygon([(fx - fh * .13, fy - fh * .76), (fx - fh * .30, fy - fh * .40), (fx - fh * .18, fy - fh * .34), (fx - fh * .07, fy - fh * .60)], fill="#E9F0F7", outline="#000000")
    d.polygon([(fx + fh * .13, fy - fh * .76), (fx + fh * .30, fy - fh * .40), (fx + fh * .18, fy - fh * .34), (fx + fh * .07, fy - fh * .60)], fill="#E9F0F7", outline="#000000")
    d.polygon([(fx - hr * 1.3, hy - hr * .6), (fx, hy - hr * 1.4), (fx + hr * 1.3, hy - hr * .6), (fx + hr * 1.5, hy + hr * 7),
               (fx + hr * .9, hy + hr * 6.6), (fx + hr * .85, hy), (fx - hr * .85, hy), (fx - hr * .9, hy + hr * 6.6), (fx - hr * 1.5, hy + hr * 7)], fill="#020305")
    d.ellipse([fx - hr, hy - hr * .9, fx + hr, hy + hr * 1.1], fill="#F4F8FB")
    eyes = [(fx - hr * .38, hy + hr * .05), (fx + hr * .38, hy + hr * .05)]
    for ex, ey in eyes:
        glow(img, ex, ey, 11, (225, 20, 20), 1.0, blur=12)
    d = ImageDraw.Draw(img)
    for ex, ey in eyes:
        d.ellipse([ex - 7, ey - 4, ex + 7, ey + 4], fill="#FF2A2A")
    fog(img, .60, .86, .30, seed, color=(190, 205, 225))
    layer = Image.new("L", img.size, 0)                  # falling snow
    ld = ImageDraw.Draw(layer)
    for _ in range(260):
        x, y, r = rnd.uniform(0, CW), rnd.uniform(0, CH), rnd.choice((2, 3, 3, 4, 6))
        ld.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(120, 230))
    img.paste(Image.new("RGB", img.size, (235, 242, 250)), (0, 0), layer.filter(ImageFilter.GaussianBlur(1.2)))
    hatch(img, alpha=26)
    return img, {"eyes": eyes, "hot": (fx, hy)}


def art_shrine(seed=11):
    rnd = random.Random(seed)
    img = grad("#05100E", "#1E3A36")
    glow(img, .5 * CW, .30 * CH, 300, (60, 100, 90), .6, blur=260)
    d = ImageDraw.Draw(img)
    for k in range(18):                                   # background cedars
        x = rnd.uniform(0, 1) * CW
        w = rnd.uniform(18, 34)
        d.polygon([(x - w, CH), (x - w * .7, .1 * CH), (x + w * .7, .1 * CH), (x + w, CH)], fill="#0A1A16")
    fog(img, .35, .70, .30, seed, color=(140, 180, 165))
    d = ImageDraw.Draw(img)
    vx = .5 * CW
    d.polygon([(vx - .06 * CW, .52 * CH), (vx + .06 * CW, .52 * CH), (CW * .85, CH), (CW * .15, CH)], fill="#1A2B28", outline="#000000")
    for k in range(9):                                    # stone steps
        t = k / 9
        y = (.54 + .44 * t ** 1.4) * CH
        w = (.07 + .33 * t ** 1.4) * CW
        d.line([vx - w, y, vx + w, y], fill="#30463F", width=int(4 + 10 * t))
    for tx, ty, s_ in ((.5, .50, .32), (.5, .55, .55)):   # torii gates in perspective
        w, h = s_ * CW * .55, s_ * CH * .30
        cx, cy = tx * CW, ty * CH
        col = "#B11C1C" if s_ > .4 else "#8C1717"
        for sx in (-1, 1):
            d.rectangle([cx + sx * w * .8 - w * .07, cy - h, cx + sx * w * .8 + w * .07, cy + h * .35], fill=col, outline="#000000", width=5)
        d.polygon([(cx - w * 1.15, cy - h * 1.02), (cx + w * 1.15, cy - h * 1.02), (cx + w * 1.0, cy - h * .84), (cx - w * 1.0, cy - h * .84)], fill="#0D0D0D", outline="#000000")
        d.rectangle([cx - w * .95, cy - h * .72, cx + w * .95, cy - h * .6], fill=col, outline="#000000", width=4)
    glow(img, vx, .52 * CH, 90, (225, 20, 20), .55, blur=90)
    d = ImageDraw.Draw(img)
    for sx in (-1, 1):                                    # stone lanterns
        lx, ly = vx + sx * .30 * CW, .74 * CH
        d.rectangle([lx - 16, ly, lx + 16, ly + 130], fill="#2A3B36", outline="#000000", width=4)
        d.rectangle([lx - 44, ly - 56, lx + 44, ly], fill="#34483F", outline="#000000", width=4)
        d.rectangle([lx - 22, ly - 36, lx + 22, ly - 8], fill="#E9C46A")
        d.polygon([(lx - 62, ly - 56), (lx, ly - 104), (lx + 62, ly - 56)], fill="#233630", outline="#000000")
        glow(img, lx, ly - 22, 50, (190, 150, 60), .8, blur=50)
        d = ImageDraw.Draw(img)
    hy = .46 * CH                                          # a small figure between the gates
    d.polygon([(vx - 13, hy + 100), (vx + 13, hy + 100), (vx + 22, hy + 210), (vx - 22, hy + 210)], fill="#010203")
    d.ellipse([vx - 12, hy + 70, vx + 12, hy + 100], fill="#010203")
    eyes = [(vx - 5, hy + 84), (vx + 5, hy + 84)]
    for ex, ey in eyes:
        glow(img, ex, ey, 7, (225, 20, 20), 1.0, blur=8)
    fog(img, .72, .96, .34, seed + 1, color=(140, 175, 160))
    hatch(img)
    return img, {"hot": (vx, hy + 80), "eyes": eyes}


ARTS = {"school": art_school, "corridor": art_corridor, "bathroom": art_bathroom, "stall": art_stall,
        "eyes": art_eyes, "girl": art_girl, "forest": art_forest, "mask": art_mask, "street": art_street, "snow": art_snow, "shrine": art_shrine}


def make_art(name, seed=1):
    if name == "corridor_figure":
        return art_corridor(seed, figure=True)
    if name == "street_figure":
        return art_street(seed, figure=True)
    if name == "bathroom_empty":
        return art_bathroom(seed, eyes=False)
    return ARTS[name](seed)
