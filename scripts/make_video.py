#!/usr/bin/env python3
"""make_video.py — renders the Quest Book promo video for the landing page (docs/).

Run from the repo root:
    python3 scripts/make_video.py            # all scenes -> docs/quest-book-promo.mp4 (+ poster jpg)
    python3 scripts/make_video.py still story 5.0 build/video/x.jpg   # one preview frame
    python3 scripts/make_video.py scene story                          # one scene file only
    python3 scripts/make_video.py join                                 # concat scene files

Needs Pillow, numpy, ffmpeg and ImageMagick `convert` (same as make_logo.py). The figures come
straight from make_logo.py, so the video always matches the logo. 1920x1080, 30 fps, with a
synthesized soundtrack (music + effects timed to the scenes; `join` rebuilds only the sound).
Drop SpecialElite-Regular.ttf / ShareTechMono-Regular.ttf into assets/fonts/ to use the site's
real fonts; otherwise close typewriter/mono fallbacks are used.
"""
import os, sys, math, random, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = f"{ROOT}/build/video"
FINAL = f"{ROOT}/docs/quest-book-promo.mp4"
POSTER = f"{ROOT}/docs/quest-book-promo-poster.jpg"
os.makedirs(WORK, exist_ok=True)

def C(h):
    h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
BG, PANEL, LINE = C("0f0d0a"), C("141008"), C("2a2010")
AMBER, AMBER_S, AMBER_H = C("d4a843"), C("b89a6a"), C("f0d890")
PARCH, MUTED, BODY2 = C("c8b49a"), C("6a5a42"), C("a99878")
BTN, BTN_B, BTN_T = C("161208"), C("3a2e14"), C("b8a07a")
GREEN, RED, GOLD = C("7fd17f"), C("e07a7a"), C("f0c95a")

def mix(a, b, t):
    t = max(0.0, min(1.0, t)); return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))

# ---------------------------------------------------------------- fonts
def _first(*paths):
    for p in paths:
        if os.path.exists(p): return p
    return None
SERIF = _first(f"{ROOT}/assets/fonts/SpecialElite-Regular.ttf",
               "/usr/share/texmf/fonts/opentype/public/lm/lmmono10-regular.otf",
               "/System/Library/Fonts/Supplemental/Courier New.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
MONO = _first(f"{ROOT}/assets/fonts/ShareTechMono-Regular.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/System/Library/Fonts/Menlo.ttc")
MONOB = _first("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", MONO)
_fc = {}
def F(path, size):
    k = (path, size)
    if k not in _fc: _fc[k] = ImageFont.truetype(path, size)
    return _fc[k]
def title_font(s, size):
    """Typewriter face for Latin titles; mono-bold when the text needs glyphs it lacks (Cyrillic)."""
    return F(MONOB, int(size * 0.84)) if any(ord(ch) > 0x250 for ch in s) else F(SERIF, size)

# ---------------------------------------------------------------- easing / helpers
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ramp(t, t0, d): return clamp((t - t0) / d) if d > 0 else float(t >= t0)
def ease(x): x = clamp(x); return 1 - (1 - x) ** 3
def smooth(x): x = clamp(x); return x * x * (3 - 2 * x)

def make_bg():
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W / 2) / (W * 0.72)) ** 2 + ((y + 60) / (H * 0.95)) ** 2)
    g = np.clip(1 - d, 0, 1) ** 1.6
    base, glow = np.array(BG, np.float32), np.array((38, 30, 15), np.float32)
    img = base + (glow - base) * g[..., None]
    img += np.random.RandomState(7).uniform(-0.5, 0.5, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
BGIMG = make_bg()

_pc = {}
def panel(w, h, fill, border=None, r=8, accent=None, bw=2):
    k = (w, h, fill, border, r, accent, bw)
    if k not in _pc:
        S = 3
        im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, w * S - 1, h * S - 1), r * S, fill=fill + (255,),
                            outline=(border + (255,)) if border else None, width=bw * S)
        if accent:
            d.rectangle((0, 0, 5 * S, h * S), fill=accent + (255,))
        _pc[k] = im.resize((w, h), Image.LANCZOS)
    return _pc[k]

def put(img, im, x, y, a=1.0):
    if a <= 0.004: return
    if a >= 0.996: img.paste(im, (int(round(x)), int(round(y))), im)
    else: img.paste(im, (int(round(x)), int(round(y))), im.getchannel("A").point(lambda v: int(v * a)))

def text(d, xy, s, font, fill, a=1.0, anchor="la", base=BG):
    if a <= 0.004: return
    d.text(xy, s, font=font, fill=mix(base, fill, a), anchor=anchor)

def tracked(d, x, y, s, font, fill, track, a=1.0, center=False, n=None, base=BG):
    widths = [font.getlength(ch) + track for ch in s]
    if center: x -= (sum(widths) - track) / 2
    for i, ch in enumerate(s):
        if n is None or i < n: text(d, (x, y), ch, font, fill, a, base=base)
        x += widths[i]

def wrap(s, font, maxw):
    lines, cur = [], ""
    for word in s.split(" "):
        t = (cur + " " + word).strip()
        if font.getlength(t) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = word
    if cur: lines.append(cur)
    return lines

def typed(d, x, y, lines, font, fill, lh, n, base=BG, caret=False, t=0):
    cx, cy = x, y
    for i, ln in enumerate(lines):
        if n <= 0: break
        part = ln[:n]; text(d, (x, y + i * lh), part, font, fill, base=base)
        cx, cy = x + font.getlength(part), y + i * lh
        n -= len(ln) + 1
    if caret and int(t * 2.5) % 2 == 0:
        d.rectangle((cx + 3, cy + 2, cx + 6, cy + font.size + 2), fill=AMBER)

def badge(img, d, x, y, label, a=1.0, right=False):
    cols = {"EASY": (C("1f3a1f"), GREEN), "NORMAL": (C("3a2e10"), C("e8b94a")), "HARD": (C("3a1414"), RED)}
    bgc, fg = cols[label]; f = F(MONO, 20)
    w = int(f.getlength(label)) + 30
    if right: x -= w
    put(img, panel(w, 32, bgc, mix(bgc, fg, 0.45), r=16, bw=1), x, y, a)
    text(d, (x + w / 2, y + 16), label, f, fg, a, "mm", base=bgc)
    return w

def cursor(img, x, y):
    pts = [(0, 0), (0, 26), (7, 20), (12, 31), (16, 29), (11, 18), (20, 18)]
    S = 1.5; d = ImageDraw.Draw(img)
    d.polygon([(x + px * S + 2, y + py * S + 3) for px, py in pts], fill=(0, 0, 0))
    d.polygon([(x + px * S, y + py * S) for px, py in pts], fill=(240, 232, 215), outline=(20, 16, 10))

# ---------------------------------------------------------------- logo assets (from make_logo.py)
K0 = 2.6
FIGS = ["WIZARD", "ASTRONAUT", "PIRATE", "DETECTIVE", "KNIGHT", "ROBOT", "COWBOY", "SAMURAI", "ARCHER"]
TRIOS = [FIGS[0:3], FIGS[3:6], FIGS[6:9]]
SLOTS = [(150, 284, 0.95), (262, 304, 1.0), (374, 284, 0.95)]
def build_assets():
    src = open(f"{ROOT}/scripts/make_logo.py").read().split("\nroot = ")[0]   # skip its file-writing tail
    ns = {}; exec(src, ns)
    def render(name, vb, body):
        w, h = int(vb[2] * K0), int(vb[3] * K0)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">{body}</svg>')
        open(f"{WORK}/{name}.svg", "w").write(svg)
        subprocess.run(["convert", "-background", "none", f"{WORK}/{name}.svg", "-resize", f"{w}x{h}!",
                        f"{WORK}/{name}.png"], check=True)
    render("book", (40, 70, 440, 310), ns["BOOK"])
    render("stars", (40, 70, 440, 310), ns["star"](198, 112, 9) + ns["star"](214, 92, 5) + ns["star"](168, 100, 4, "#e8dcc0"))
    for n in FIGS:
        render(n.lower(), (-60, -185, 120, 200), ns["figure"](ns[n], 0, 0, 1))
_ac = {}
def asset(name, w, h):
    k = (name, w, h)
    if k not in _ac:
        p = f"{WORK}/{name}.png"
        if not os.path.exists(p): build_assets()
        _ac[k] = Image.open(p).convert("RGBA").resize((w, h), Image.LANCZOS)
    return _ac[k]

def pop(t, t0):
    """The site's pop-up: scaleY 0 -> 1.08 -> 1."""
    x = t - t0
    if x <= 0: return 0.0
    if x < 0.24: return 1.08 * ease(x / 0.24)
    if x < 0.36: return 1.08 - 0.08 * (x - 0.24) / 0.12
    return 1.0
def fold(t, t0): return 1.0 - smooth(ramp(t, t0, 0.22))

def draw_logo(img, cx, y0, K, pops, spark=1.0, a=1.0):
    """pops: [(trio_index, (p_left, p_centre, p_right)), ...]"""
    ox = cx - 220 * K
    put(img, asset("book", int(440 * K), int(310 * K)), ox, y0, a)
    for ti, ps in pops:
        for k, (x, y, s) in enumerate(SLOTS):
            p = ps[k]
            if p <= 0.02: continue
            fw, fh = int(120 * K * s), int(200 * K * s)
            im = asset(TRIOS[ti][k].lower(), fw, fh)
            if abs(p - 1) > 0.004: im = im.resize((fw, max(1, int(fh * p))), Image.BILINEAR)
            put(img, im, ox + (x - 40) * K - 60 * K * s, y0 + (y - 70) * K - 185 * K * s * p, a)
    put(img, asset("stars", int(440 * K), int(310 * K)), ox, y0, a * spark)

# ---------------------------------------------------------------- dice
_dc = {}
def die(face, size):
    k = (face, size)
    if k not in _dc:
        S = 3; n = size * S
        im = Image.new("RGBA", (n, n), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, n - 1, n - 1), n * 0.17, fill=C("1c1608") + (255,), outline=AMBER + (255,), width=int(n * 0.035))
        q, r = n * 0.27, n * 0.085
        spots = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)], 4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
                 5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)], 6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}[face]
        for sx, sy in spots:
            cx, cy = n / 2 + sx * q, n / 2 + sy * q
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD + (255,))
        _dc[k] = im.resize((size, size), Image.LANCZOS)
    return _dc[k]

def tumble(t, t0, result, seed):
    """Like the app's animate_roll: 18 random faces, slowing down. -> (face, tilt, hop, landed_for)"""
    rng = random.Random(seed); x = t - t0; acc = 0.0
    tilts = (-14, 10, -6, 12, -10, 6)
    if x < 0: return rng.randint(1, 6), -8, 0, -1
    for i in range(18):
        face = rng.randint(1, 6); step = 0.055 + i * 0.006
        if x < acc + step:
            ph = (x - acc) / step
            return face, tilts[i % 6], -26 * math.sin(math.pi * ph) * (1 - i / 22), -1
        acc += step
    return result, 0, 0, x - acc

def draw_die(img, cx, cy, t, t0, result, seed, size=210):
    face, tilt, hop, landed = tumble(t, t0, result, seed)
    s = size
    if landed >= 0: s = int(size * (1 + 0.14 * math.exp(-landed * 9) * math.cos(landed * 20)))
    im = die(face, s)
    if tilt: im = im.rotate(tilt, resample=Image.BICUBIC, expand=True)
    put(img, im, cx - im.width / 2, cy - im.height / 2 + hop)
    return landed

def hpbar(img, d, x, y, w, hp, maxhp, label=True, base=PANEL):
    put(img, panel(w, 22, C("0c0a07"), LINE, r=11, bw=1), x, y)
    fw = max(22, int((w - 6) * hp / maxhp))
    col = mix(C("b0563f"), C("6f9a52"), clamp((hp / maxhp - 0.3) / 0.6))
    put(img, panel(fw, 16, col, None, r=8), x + 3, y + 3)
    if label: text(d, (x + w, y - 12), f"{int(round(hp))} / {maxhp}", F(MONO, 26), AMBER, anchor="rs", base=base)

# ================================================================= scenes
def sc_intro(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img)
    K = 2.3; a = ease(ramp(t, 0.0, 0.6)); y0 = 70 + (1 - a) * 40
    pops = [(0, tuple(pop(t, 0.55 + 0.18 * k) * fold(t, 3.25 + 0.05 * k) for k in range(3))),
            (1, tuple(pop(t, 3.55 + 0.18 * k) for k in range(3)))]
    spark = 0.65 + 0.35 * math.cos((t - 1.0) * 2.6) if t > 1.0 else ramp(t, 0.7, 0.3)
    draw_logo(img, W / 2, y0, K, pops, spark, a)
    title = "QUEST BOOK"
    tracked(d, W / 2, 800, title, F(SERIF, 124), AMBER, 16, center=True, n=int(ramp(t, 1.25, 0.8) * len(title) + 0.999) if t > 1.25 else 0)
    tag = "Your choices. Your dice. Your story."
    n = int(ramp(t, 2.3, 1.3) * len(tag))
    f = F(SERIF, 46); x0 = W / 2 - f.getlength(tag) / 2
    typed(d, x0, 950, [tag], f, AMBER_S, 0, n, caret=(2.3 < t < 4.2), t=t)
    return img

HERO = {"hp": 22, "str": 3, "agi": 8, "sta": 6}
def hero_panel(img, d, x, y, hp=22, a=1.0):
    w = 440
    put(img, panel(w, 500, PANEL, LINE, r=8), x, y, a)
    if a < 0.5: return
    tracked(d, x + 30, y + 28, "YOUR HERO", F(MONO, 22), MUTED, 4, base=PANEL)
    text(d, (x + 30, y + 86), "HP", F(MONO, 26), MUTED, base=PANEL)
    hpbar(img, d, x + 30, y + 126, w - 60, hp, 22)
    for i, (lab, key) in enumerate((("STR", "str"), ("AGI", "agi"), ("STA", "sta"))):
        tx = x + 30 + i * 130
        put(img, panel(120, 110, C("0f0c06"), LINE, r=8, bw=1), tx, y + 180)
        text(d, (tx + 60, y + 212), lab, F(MONO, 22), MUTED, anchor="mm", base=C("0f0c06"))
        text(d, (tx + 60, y + 256), str(HERO[key]), F(MONO, 40), AMBER, anchor="mm", base=C("0f0c06"))
    tracked(d, x + 30, y + 330, "PACK", F(MONO, 22), MUTED, 4, base=PANEL)
    f = F(MONO, 24)
    for i, it in enumerate(("Oil Lantern", "Map to the gate")):
        cw = int(f.getlength(it)) + 36
        put(img, panel(cw, 44, C("1e1a0e"), C("5a4520"), r=22, bw=1), x + 30, y + 372 + i * 56)
        text(d, (x + 48, y + 394 + i * 56), it, f, AMBER, anchor="lm", base=C("1e1a0e"))

DESC = ("A toothed iron gate yawns at the bottom of the chapel stairs. Cold air breathes out of the "
        "dark, carrying a faint, dry whispering. Worn steps lead down; to one side, a rusted grille "
        "hides a narrower shortcut.")
def story_header(img, d, a=1.0):
    f = F(MONO, 26)
    tracked(d, 140, 78, "THE WHISPERING CATACOMBS", f, AMBER_S, 5, a)
    badge(img, d, 140 + int(f.getlength("THE WHISPERING CATACOMBS")) + 24 * 5 + 28, 76, "EASY", a)
    d.line((140, 136, W - 140, 136), fill=mix(BG, LINE, a), width=2)

def sc_story(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img)
    story_header(img, d)
    text(d, (140, 176), "The Crypt Gate", F(SERIF, 76), AMBER, ease(ramp(t, 0.2, 0.4)))
    put(img, panel(1100, 310, PANEL, None, r=4, accent=C("8b6914")), 140, 296, ease(ramp(t, 0.35, 0.35)))
    f = F(MONO, 33); lines = wrap(DESC, f, 1020)
    typed(d, 184, 326, lines, f, PARCH, 52, int(ramp(t, 0.7, 2.7) * len(DESC)), base=PANEL, caret=(0.7 < t < 3.5), t=t)
    hero_panel(img, d, 1340, 176, a=ease(ramp(t, 0.3, 0.4)))
    tracked(d, 140, 648, "WHAT DO YOU DO?", F(MONO, 22), MUTED, 4, ease(ramp(t, 3.5, 0.3)))
    hover = ramp(t, 5.55, 0.15); click = ramp(t, 6.25, 0.1) * (1 - ramp(t, 6.4, 0.25))
    opts = [("Descend the worn stairs into the hall", None), ("Force the rusted grille for a shortcut", "STRENGTH CHECK")]
    for i, (lab, tag) in enumerate(opts):
        a = ease(ramp(t, 3.7 + 0.3 * i, 0.35)); y = 698 + i * 104 + (1 - a) * 18
        hv = hover if i == 1 else 0
        fill = mix(mix(BTN, C("201a0c"), hv), C("3a2e12"), click if i == 1 else 0)
        put(img, panel(1100, 84, fill, mix(BTN_B, AMBER, hv), r=6), 140, y, a)
        text(d, (176, y + 42), lab, F(MONO, 31), mix(BTN_T, AMBER_H, hv), a, "lm", base=fill)
        if tag: tracked(d, 1210 - F(MONO, 20).getlength(tag) - 3 * len(tag), y + 31, tag, F(MONO, 20), mix(MUTED, AMBER, hv), 3, a, base=fill)
    if t > 4.3:
        m = smooth(ramp(t, 4.5, 1.0))
        cursor(img, 1500 + (930 - 1500) * m, 1000 + (866 - 1000) * m - 60 * math.sin(math.pi * m))
    return img

def challenge(img, d, t, kind, title, sub, dc, result, seed, accent, t_roll=1.0):
    """Shared challenge card: caption, title, formula, tumbling die, sum. Returns time since landing."""
    cw, ch, cx0, cy0 = 1180, 760, (W - 1180) // 2, 170
    a = ease(ramp(t, 0.0, 0.35))
    put(img, panel(cw, ch, C("100d08"), LINE, r=8, accent=accent), cx0, cy0 + (1 - a) * 24, a)
    if a < 0.6: return -1
    B = C("100d08"); mx = W / 2
    tracked(d, mx, cy0 + 44, kind, F(MONO, 24), mix(MUTED, accent, 0.5), 6, center=True, base=B)
    text(d, (mx, cy0 + 130), title, F(SERIF, 62), accent if kind != "STRENGTH CHECK" else AMBER, anchor="mm", base=B)
    text(d, (mx, cy0 + 200), sub, F(MONO, 28), BODY2, ramp(t, 0.3, 0.3), "mm", base=B)
    landed = draw_die(img, mx, cy0 + 390, t, t_roll, result, seed)
    fa = ramp(t, 0.5, 0.3)
    if landed < 0.35:
        text(d, (mx, cy0 + 560), f"roll 1d6 + STR {HERO['str']}  —  need {dc}", F(MONO, 34), PARCH, fa, "mm", base=B)
    else:
        tot = result + HERO["str"]
        text(d, (mx, cy0 + 560), f"{result} + {HERO['str']} = {tot}   {'≥' if tot >= dc else '<'}   {dc}", F(MONO, 40), GOLD, ramp(landed, 0.35, 0.2), "mm", base=B)
    return landed

def sc_check(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img); story_header(img, d)
    landed = challenge(img, d, t, "STRENGTH CHECK", "Force the rusted grille", "Brute strength against old iron.", 7, 5, 11, C("8b6914"))
    if landed > 0.8:
        a = ease(ramp(landed, 0.8, 0.3)); B = C("100d08")
        tracked(d, W / 2, 170 + 622, "SUCCESS", F(SERIF, 60), GREEN, 10, a, center=True, base=B)
        text(d, (W / 2, 170 + 716), "The grille shrieks — and gives way.", F(MONO, 28), BODY2, ramp(landed, 1.2, 0.3), "mm", base=B)
    return img

def sc_monster(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img); story_header(img, d)
    _, _, _, l0 = tumble(t, 1.1, 2, 5)
    shake = 0
    if l0 > 0.8: shake = int(14 * math.exp(-(l0 - 0.8) * 7) * math.sin((l0 - 0.8) * 60))
    if shake:
        base = img; img = BGIMG.copy(); d = ImageDraw.Draw(img); story_header(img, d)
    landed = challenge(img, d, t, "A MONSTER BARS THE WAY", "Bone Sentinel", "Ten thousand skulls watch from the walls.", 9, 2, 5, C("b0563f"), t_roll=1.1)
    B = C("100d08")
    hp = 22 - 6 * smooth(ramp(landed, 0.9, 0.5)) if landed > 0 else 22
    if landed > 0.8:
        a = ease(ramp(landed, 0.8, 0.25))
        tracked(d, W / 2 - 250, 170 + 622, "−6 HP", F(MONOB, 54), RED, 4, a, center=True, base=B)
    text(d, (W / 2 + 20, 170 + 664), "HP", F(MONO, 26), MUTED, ramp(t, 0.4, 0.3), "ls", base=B)
    if t > 0.5: hpbar(img, d, W / 2 + 20, 170 + 690, 500, hp, 22, base=B)
    if shake:
        out = BGIMG.copy(); out.paste(img, (shake, 0)); img = out
    return img

LIB = [("The Whispering Catacombs", "Gothic dungeon crawl", "EASY", "12 locations"),
       ("Silent Run: The Hyperion Drift", "Derelict generation ship", "NORMAL", "15 locations"),
       ("The Banshee's Wail", "Pirate ghost ship", "HARD", "22 locations"),
       ("Dust and Rust: The Salt Flat Run", "Post-apocalyptic wasteland", "NORMAL", "32 locations"),
       ("Escape de la Hacienda", "Huida de un cártel", "NORMAL", "Español · B1"),
       ("Исход из хрущёвки", "Митьковский тупик", "HARD", "Русский · C2")]
def chips(img, d, x, y, labels, sel, t, t_sel, w=None, gap=14):
    f = F(MONO, 26)
    for i, lab in enumerate(labels):
        cw = w or int(f.getlength(lab)) + 44
        on = ramp(t, t_sel, 0.15) if i == sel else 0
        fill = mix(BTN, C("2a2210"), on)
        put(img, panel(cw, 54, fill, mix(BTN_B, AMBER, on), r=6), x, y)
        text(d, (x + cw / 2, y + 27), lab, f, mix(BTN_T, AMBER_H, on), anchor="mm", base=fill)
        x += cw + gap

def sc_create(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img)
    text(d, (140, 84), "Create a New Story", F(SERIF, 72), AMBER, ease(ramp(t, 0.1, 0.4)))
    text(d, (140, 182), "Type a theme — the engine writes a full quest.", F(MONO, 28), BODY2, ease(ramp(t, 0.3, 0.4)))
    a = ease(ramp(t, 0.25, 0.4)); fx, fy, fw = 140, 262, 760
    put(img, panel(fw, 700, PANEL, LINE, r=8), fx, fy, a)
    if a > 0.6:
        lab = F(MONO, 22); x = fx + 40
        tracked(d, x, fy + 40, "THEME", lab, MUTED, 4, base=PANEL)
        put(img, panel(fw - 80, 68, C("1a150b"), mix(BTN_B, AMBER, 0.6 if t < 2.4 else 0), r=6), x, fy + 76)
        theme = "haunted Mars colony"
        typed(d, x + 22, fy + 92, [theme], F(MONO, 32), PARCH, 0, int(ramp(t, 0.9, 1.4) * len(theme)), base=C("1a150b"), caret=(0.6 < t < 2.4), t=t)
        tracked(d, x, fy + 186, "DIFFICULTY", lab, MUTED, 4, base=PANEL)
        chips(img, d, x, fy + 222, ["Easy", "Normal", "Hard"], 2, t, 2.6)
        tracked(d, x, fy + 318, "LANGUAGE", lab, MUTED, 4, base=PANEL)
        put(img, panel(fw - 80, 68, C("1a150b"), mix(BTN_B, AMBER, 0.6 if 2.9 < t < 3.7 else 0), r=6), x, fy + 354)
        typed(d, x + 22, fy + 370, ["Italiano"], F(MONO, 32), PARCH, 0, int(ramp(t, 3.0, 0.55) * 8), base=C("1a150b"), caret=(2.9 < t < 3.7), t=t)
        tracked(d, x, fy + 464, "READING LEVEL (CEFR)", lab, MUTED, 4, base=PANEL)
        chips(img, d, x, fy + 500, ["A1", "A2", "B1", "B2", "C1", "C2"], 2, t, 3.9, w=100, gap=16)
        on = ramp(t, 4.35, 0.15); fill = mix(C("1c1608"), C("2e240e"), on)
        put(img, panel(fw - 80, 72, fill, mix(C("3a2e14"), AMBER, on), r=6), x, fy + 596)
        text(d, (fx + fw / 2, fy + 632), "Conjure my adventure", F(MONO, 30), mix(AMBER, AMBER_H, on), anchor="mm", base=fill)
    # library, right
    lx, ly, cw, chh = 980, 262, 386, 216
    tracked(d, lx, 222, "…OR PICK ONE FROM THE LIBRARY", F(MONO, 22), MUTED, 4, ease(ramp(t, 4.6, 0.4)))
    for i, (name, theme_, diff, lang) in enumerate(LIB):
        a = ease(ramp(t, 4.75 + 0.14 * i, 0.4))
        if a <= 0: continue
        x = lx + (i % 2) * (cw + 28); y = ly + (i // 2) * (chh + 26) + (1 - a) * 30
        put(img, panel(cw, chh, PANEL, LINE, r=6, accent=C("8b6914"), bw=1), x, y, a)
        if a < 0.5: continue
        f = title_font(name, 31)
        for j, ln in enumerate(wrap(name, f, cw - 56)[:2]):
            text(d, (x + 30, y + 22 + j * 38), ln, f, AMBER, a, base=PANEL)
        text(d, (x + 30, y + 108), theme_, F(MONO, 21), MUTED, a, base=PANEL)
        bw_ = badge(img, d, x + 30, y + 156, diff, a)
        if lang: text(d, (x + 30 + bw_ + 16, y + 172), lang, F(MONO, 21), AMBER_S if "·" in lang else MUTED, a, "lm", base=PANEL)
    if 2.2 < t < 4.7:
        pts = [(2.2, 700, 1040), (2.6, 470, 520), (3.0, 640, 660), (3.9, 446, 800), (4.35, 520, 910), (4.7, 520, 910)]
        for (ta, xa, ya), (tb, xb, yb) in zip(pts, pts[1:]):
            if ta <= t <= tb:
                m = smooth(min(1, (t - ta) / max(0.01, (tb - ta) * 0.8)))
                cursor(img, xa + (xb - xa) * m, ya + (yb - ya) * m)
    return img

def sc_outro(t):
    img = BGIMG.copy(); d = ImageDraw.Draw(img)
    K = 1.9; a = ease(ramp(t, 0.0, 0.5))
    pops = [(2, tuple(pop(t, 0.4 + 0.18 * k) for k in range(3)))]
    draw_logo(img, W / 2, 40 + (1 - a) * 30, K, pops, 0.65 + 0.35 * math.cos(t * 2.6), a)
    tracked(d, W / 2, 650, "QUEST BOOK", F(SERIF, 108), AMBER, 14, ease(ramp(t, 0.6, 0.5)), center=True)
    text(d, (W / 2, 810), "A free choose-your-own-adventure RPG — in your browser.", F(MONO, 34), PARCH, ease(ramp(t, 1.0, 0.5)), "mm")
    b = ease(ramp(t, 1.5, 0.45)); bw_, bh = 720, 92; glow = 0.5 + 0.5 * math.sin((t - 1.5) * 3.2) if t > 2 else 0
    fill = mix(C("1c1608"), C("251d0b"), glow)
    put(img, panel(bw_, bh, fill, mix(C("3a2e14"), AMBER, 0.45 + 0.55 * glow), r=6), W / 2 - bw_ / 2, 890 + (1 - b) * 16, b)
    text(d, (W / 2, 936 + (1 - b) * 16), "▶ Play now · quest-book.com", F(MONO, 34), mix(AMBER, AMBER_H, glow), b, "mm", base=fill)
    return img

SCENES = [("intro", sc_intro, 5.4), ("story", sc_story, 7.0), ("check", sc_check, 5.4),
          ("monster", sc_monster, 5.7), ("create", sc_create, 7.6), ("outro", sc_outro, 5.6)]
FADE = 0.3
def frame(name, t):
    fn, dur = next((f, d) for n, f, d in SCENES if n == name)
    img = fn(t)
    a = min(ramp(t, 0, FADE), ramp(dur - t, 0, FADE))      # every scene dips to the backdrop: clean joins + loop
    return img if a >= 1 else Image.blend(BGIMG, img, smooth(a))

def render_scene(name):
    dur = next(d for n, f, d in SCENES if n == name)
    tmp, out = f"{WORK}/{name}.part.mp4", f"{WORK}/{name}.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
                          "-pix_fmt", "yuv420p", "-r", str(FPS), tmp], stdin=subprocess.PIPE)
    for i in range(int(round(dur * FPS))):
        p.stdin.write(frame(name, i / FPS).tobytes())
    p.stdin.close()
    if p.wait() != 0: sys.exit(f"ffmpeg failed on {name}")
    os.replace(tmp, out); print("scene", name, "ok")

# ================================================================= sound (all synthesized, numpy only)
SR = 44100
BPM = 90.0
def _t(dur): return np.arange(int(dur * SR)) / SR
def _f(m): return 440.0 * 2 ** ((m - 69) / 12)
def _filt(x, fc, high=False):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    g = 1 / np.sqrt(1 + (f / fc) ** 4)
    return np.fft.irfft(X * (np.sqrt(np.maximum(0, 1 - g * g)) if high else g), len(x))
def _noise(dur, rng): return rng.uniform(-1, 1, int(dur * SR))
def _att(x, ms=3):
    n = min(len(x), int(SR * ms / 1000)); x[:n] *= np.linspace(0, 1, n); return x

def s_pluck(freq, dur=1.6):
    t = _t(dur); y = np.zeros_like(t)
    for k in range(1, 9):
        if freq * k > 9000: break
        y += np.sin(2 * np.pi * freq * k * t) / k ** 1.2 * np.exp(-t * (2.0 + 1.0 * k))
    return _att(y, 4)
def s_bell(freq, dur=1.4):
    t = _t(dur); y = np.zeros_like(t)
    for r, a, dcy in ((1, 1, 4), (2.76, .45, 6), (5.4, .22, 9), (8.93, .1, 13)):
        if freq * r < 15000: y += a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * dcy)
    return _att(y, 2)
def s_pad(freq, dur):
    t = _t(dur); y = np.zeros_like(t)
    for det in (0.997, 1.0, 1.003):
        for k in (1, 2, 3): y += np.sin(2 * np.pi * freq * det * k * t + k) / k ** 2
    env = np.minimum(1, t / 0.7) * np.minimum(1, (dur - t) / 0.9)
    return y * env / 3
def s_bass(freq, dur):
    t = _t(dur)
    return _att((np.sin(2 * np.pi * freq * t) + .35 * np.sin(4 * np.pi * freq * t)) * np.exp(-t * 1.6), 8)
def s_key(rng):                                   # typewriter key
    y = _filt(_noise(0.03, rng), 1800, high=True) * np.exp(-_t(0.03) * 160)
    t = _t(0.03); y += 0.35 * np.sin(2 * np.pi * rng.uniform(2300, 3100) * t) * np.exp(-t * 220)
    y2 = _filt(_noise(0.03, rng), 500) * np.exp(-_t(0.03) * 90) * 1.5
    return _att(y + y2, 1) * rng.uniform(0.6, 1.0)
def s_pop(f0=280, f1=720, dur=0.11):              # paper figure popping up
    t = _t(dur); ph = 2 * np.pi * np.cumsum(f0 + (f1 - f0) * (t / dur) ** 0.6) / SR
    return _att(np.sin(ph) * np.exp(-t * 16) * np.minimum(1, (dur - t) / 0.02), 3)
def s_click(freq=1250, dur=0.035):
    t = _t(dur); return _att(np.sin(2 * np.pi * freq * t) * np.exp(-t * 110), 1)
def s_knock(rng, freq, dur=0.05, low=False):      # die on wood
    t = _t(dur)
    y = np.sin(2 * np.pi * freq * t) * np.exp(-t * (60 if low else 95)) + 0.5 * _filt(_noise(dur, rng), 2500) * np.exp(-t * 140)
    return _att(y, 1)
def s_whoosh(rng, dur=0.4, fc=1400):
    t = _t(dur); return _filt(_noise(dur, rng), fc) * np.sin(np.pi * t / dur) ** 2
def s_hit(rng):
    t = _t(0.6); ph = 2 * np.pi * np.cumsum(50 + 90 * np.exp(-t * 18)) / SR
    return _att(np.sin(ph) * np.exp(-t * 7) + 0.8 * _filt(_noise(0.6, rng), 700) * np.exp(-t * 22), 2)
def s_growl(dur=1.6):
    t = _t(dur); y = sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate((49, 55.3, 73.6, 98.5)))
    return y * (0.6 + 0.4 * np.sin(2 * np.pi * 7 * t)) * np.sin(np.pi * t / dur) ** 1.5 / 4

class Mix:
    def __init__(self, dur): self.b = np.zeros((int(dur * SR) + SR, 2))
    def add(self, sig, t, gain=1.0, pan=0.0):
        i = int(t * SR)
        if i < 0 or i >= len(self.b): return
        sig = sig[: len(self.b) - i]
        self.b[i:i + len(sig), 0] += sig * gain * math.cos((pan + 1) * math.pi / 4)
        self.b[i:i + len(sig), 1] += sig * gain * math.sin((pan + 1) * math.pi / 4)

def _reverb(b, wet, secs=1.8, seed=3):
    rng = np.random.RandomState(seed); n = int(secs * SR); out = b.copy()
    for ch in range(2):
        ir = rng.randn(n) * np.exp(-np.arange(n) / SR * 3.6); ir[: int(0.012 * SR)] = 0
        ir = _filt(ir, 4500); ir /= np.sqrt((ir ** 2).sum())
        m = len(b) + n; y = np.fft.irfft(np.fft.rfft(b[:, ch], m) * np.fft.rfft(ir, m), m)[: len(b)]
        out[:, ch] += wet * y
    return out

CH = {"Dm": (50, 53, 57), "Bb": (46, 50, 53), "F": (53, 57, 60), "C": (48, 52, 55),
      "Gm": (55, 58, 62), "A": (57, 61, 64), "D": (50, 54, 57)}
BARS = ["Dm", "Bb", "F", "C", "Dm", "Bb", "Gm", "A", "Dm", "Bb", "F", "C", "D", "D"]
def music(total):
    m = Mix(total); beat = 60 / BPM; bar = 4 * beat
    for bi, name in enumerate(BARS):
        t0 = bi * bar
        if t0 > total: break
        r, a3, a5 = CH[name]
        dark = name in ("Gm", "A")                             # the monster's bars: lower, heavier
        lift = 0.55 + 0.45 * min(1, bi / 2)                    # first bars come in softly
        for tone in (r, a3, a5):
            m.add(s_pad(_f(tone + (0 if dark else 12)), bar + 0.9), t0, 0.075, (tone % 3 - 1) * 0.4)
        root = r - 12 if r - 12 >= 38 else r
        m.add(s_bass(_f(root - 12), 2 * beat), t0, 0.30)
        m.add(s_bass(_f(root - 12), 1.5 * beat), t0 + 2 * beat, 0.18)
        if dark: m.add(s_bass(_f(root - 12), beat), t0 + 3 * beat, 0.16)
        pat = [r, a5, r + 12, a3 + 12, a5 + 12, a3 + 12, r + 12, a5]
        if bi == len(BARS) - 1: pat = [r, a3, a5, r + 12, a3 + 12, a5 + 12, r + 24, None]
        for k, note in enumerate(pat):
            if note is None: continue
            acc = 1.0 if k % 4 == 0 else 0.72
            m.add(s_pluck(_f(note + (0 if dark else 12))), t0 + k * beat / 2, 0.17 * acc * lift, -0.35 + 0.1 * k)
        if bi >= 4 and not dark and bi < 13:                   # a little bell line on top
            for k, off in ((0, 12), (3, 7), (6, 3 if name != "D" else 4)):
                m.add(s_bell(_f(r + 12 + off + (12 if r < 50 else 0))), t0 + k * beat / 2, 0.045, 0.3)
    return _reverb(m.b, 0.30)

def sfx(total):
    rng = np.random.RandomState(11); m = Mix(total)
    off = {}; acc = 0.0
    for n, _, d in SCENES: off[n] = acc; acc += d
    def keys(t0, t1, n, pan=0.0, gain=0.20):
        for i in range(n):
            m.add(s_key(rng), t0 + (t1 - t0) * (i + rng.uniform(-.25, .25)) / n, gain, pan + rng.uniform(-.1, .1))
    def roll(t0, pan=0.0):
        t = t0
        for i in range(18):
            m.add(s_knock(rng, rng.uniform(900, 1700)), t, 0.30 * (1 - i / 40), pan + rng.uniform(-.3, .3))
            t += 0.055 + i * 0.006
        m.add(s_knock(rng, 210, 0.16, low=True), t, 0.55); m.add(s_knock(rng, 1200), t, 0.25)
        return t
    # intro
    o = off["intro"]
    m.add(s_whoosh(rng, 0.7, 900), o, 0.10)
    for k in range(3): m.add(s_pop(260 + 60 * k, 700 + 110 * k), o + 0.55 + 0.18 * k, 0.32, -0.5 + 0.5 * k)
    for i in range(9): m.add(s_click(700 + 55 * i, 0.05), o + 1.25 + 0.8 * i / 9, 0.10)
    keys(o + 2.3, o + 3.6, 22)
    m.add(s_pop(620, 240, 0.16), o + 3.27, 0.20)
    for k in range(3): m.add(s_pop(300 + 60 * k, 760 + 110 * k), o + 3.55 + 0.18 * k, 0.32, -0.5 + 0.5 * k)
    # story
    o = off["story"]
    keys(o + 0.7, o + 3.4, 40, -0.3, 0.17)
    for i in range(2): m.add(s_pop(420 + 90 * i, 560 + 90 * i, 0.07), o + 3.7 + 0.3 * i, 0.16, -0.3)
    m.add(s_click(1500, 0.03), o + 5.6, 0.10, -0.2)
    m.add(s_click(980, 0.04), o + 6.25, 0.30, -0.2); m.add(s_knock(rng, 300, 0.06, low=True), o + 6.25, 0.22, -0.2)
    # strength check
    o = off["check"]
    m.add(s_whoosh(rng, 0.45), o, 0.12)
    land = roll(o + 1.0)
    for i, note in enumerate((74, 78, 81, 86)): m.add(s_bell(_f(note), 1.6), land + 0.8 + 0.085 * i, 0.20, -0.3 + 0.2 * i)
    # monster
    o = off["monster"]
    m.add(s_whoosh(rng, 0.5, 600), o, 0.16); m.add(s_growl(1.9), o + 0.15, 0.50)
    land = roll(o + 1.1)
    m.add(s_hit(rng), land + 0.8, 0.85)
    for i, note in enumerate((57, 56, 50)): m.add(s_pluck(_f(note), 1.2), land + 0.95 + 0.16 * i, 0.26)
    # create
    o = off["create"]
    keys(o + 0.9, o + 2.3, 19, -0.4); m.add(s_click(980, 0.04), o + 2.6, 0.26, -0.4)
    keys(o + 3.0, o + 3.55, 8, -0.4); m.add(s_click(980, 0.04), o + 3.9, 0.26, -0.4)
    m.add(s_click(820, 0.05), o + 4.35, 0.32, -0.4); m.add(s_knock(rng, 260, 0.07, low=True), o + 4.35, 0.25, -0.4)
    for i in range(14):                                           # the conjuring sparkle
        m.add(s_bell(_f(74 + [0, 3, 5, 7, 10, 12, 15, 17][rng.randint(8)] + 12), 0.7), o + 4.4 + 0.035 * i + rng.uniform(0, .02), 0.055, rng.uniform(-.6, .6))
    for i in range(6): m.add(s_pop(380 + 45 * i, 520 + 45 * i, 0.07), o + 4.75 + 0.14 * i, 0.15, 0.2 + 0.4 * (i % 2))
    # outro
    o = off["outro"]
    for k in range(3): m.add(s_pop(300 + 60 * k, 760 + 110 * k), o + 0.4 + 0.18 * k, 0.32, -0.5 + 0.5 * k)
    for i, note in enumerate((74, 78, 81, 86, 90)): m.add(s_bell(_f(note), 2.4), o + 1.5 + 0.09 * i, 0.13, -0.4 + 0.2 * i)
    return _reverb(m.b, 0.10, 0.9, seed=5)

def make_audio(path):
    import wave
    total = sum(d for _, _, d in SCENES); n = int(total * SR)
    mus, fx = music(total)[:n], sfx(total)[:n]
    t = np.arange(n) / SR
    duck = np.ones(n)                                             # pull the music back under the dice scenes
    acc = 0.0
    for name, _, d in SCENES:
        if name in ("check", "monster"):
            duck = np.minimum(duck, 1 - 0.4 * np.clip((t - acc) / 0.4, 0, 1) * np.clip((acc + d - t) / 0.4, 0, 1))
        acc += d
    mix = mus * duck[:, None] * 1.0 + fx * 0.95
    env = np.minimum(1, t / 0.4) * np.minimum(1, (total - t) / 1.3)   # in and out with the picture, so it loops
    mix = np.tanh(mix * env[:, None] * 1.9) * 0.89
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype("<i2").tobytes())

def join():
    lst = f"{WORK}/list.txt"
    open(lst, "w").write("".join(f"file '{WORK}/{n}.mp4'\n" for n, _, _ in SCENES))
    silent, wav, tmp = f"{WORK}/silent.mp4", f"{WORK}/soundtrack.wav", f"{WORK}/final.part.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent], check=True)
    make_audio(wav)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", tmp], check=True)
    os.replace(tmp, FINAL)
    frame("outro", 4.0).save(POSTER, quality=90)
    print("wrote", FINAL, POSTER)

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "assets": build_assets()
    elif a and a[0] == "still": frame(a[1], float(a[2])).save(a[3], quality=92)
    elif a and a[0] == "scene": render_scene(a[1])
    elif a and a[0] == "join": join()
    else:
        for n, _, _ in SCENES: render_scene(n)
        join()
