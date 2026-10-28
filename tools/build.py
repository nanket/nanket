#!/usr/bin/env python3
"""Builds the profile README: every image in assets/ and README.md itself.

Each image is a self-contained SVG. Fonts are subset and inlined, icons and
screenshots are inlined as data URIs, and all motion is plain CSS, so GitHub
renders it through a normal <img>. Images that sit on the page background come
in -dark and -light versions and are switched with <picture>.

Needs fonttools, brotli and Pillow:  python3 tools/build.py
"""
import base64
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
ASSETS = ROOT / "assets"

# --------------------------------------------------------------------------- fonts

FONT_FILES = {
    "display": ("BricolageGrotesque-800.woff2", None),
    "serif": ("InstrumentSerif-400i.woff2", None),
    "ui": ("Inter-var.woff2", {"wght": 400}),
    "ui6": ("Inter-var.woff2", {"wght": 600}),
    "mono": ("JetBrainsMono-var.woff2", {"wght": 400}),
    "mono7": ("JetBrainsMono-var.woff2", {"wght": 700}),
}
FAMILY = {key: "nk" + key.capitalize() for key in FONT_FILES}
FONT_BYTES, FONTS, CMAPS = {}, {}, {}
for key, (name, location) in FONT_FILES.items():
    font = TTFont(TOOLS / "fonts" / name)
    if location:
        font = instancer.instantiateVariableFont(font, location)
    font.flavor = None
    font.recalcTimestamp = False
    buf = io.BytesIO()
    font.save(buf)
    FONT_BYTES[key] = buf.getvalue()
    FONTS[key] = TTFont(io.BytesIO(FONT_BYTES[key]))
    CMAPS[key] = FONTS[key].getBestCmap()


def width(key, text, size, ls=0):
    font, cmap = FONTS[key], CMAPS[key]
    upm = font["head"].unitsPerEm
    advance = sum(font["hmtx"][cmap.get(ord(c), ".notdef")][0] for c in text)
    return advance * size / upm + ls * max(len(text) - 1, 0)


def font_css(used):
    rules = []
    for key, chars in sorted(used.items()):
        font = TTFont(io.BytesIO(FONT_BYTES[key]), recalcTimestamp=False)  # same bytes on every build
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern", "liga", "calt"]
        options.name_IDs = []
        sub = subset.Subsetter(options)
        sub.populate(text="".join(sorted(chars)) + " ")
        sub.subset(font)
        font.flavor = "woff2"
        buf = io.BytesIO()
        font.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        rules.append(f"@font-face{{font-family:'{FAMILY[key]}';src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return "".join(rules)


# --------------------------------------------------------------------------- svg

class SVG:
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.body, self.defs, self.css, self.used = [], [], [], {}

    def __lshift__(self, markup):
        self.body.append(markup)
        return self

    def text(self, x, y, s, key, size, fill, anchor="start", ls=0, attrs=""):
        self.used.setdefault(key, set()).update(s)
        extra = f' text-anchor="{anchor}"' if anchor != "start" else ""
        extra += f' letter-spacing="{ls}"' if ls else ""
        extra += f" {attrs}" if attrs else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FAMILY[key]}" font-size="{size}" '
                f'fill="{fill}"{extra}>{escape(s)}</text>')

    def save(self, name):
        markup = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.title)}">'
            f"<title>{escape(self.title)}</title>"
            f"<style>{font_css(self.used)}{''.join(self.css)}</style>"
            f"<defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>"
        )
        path = ASSETS / f"{name}.svg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markup)
        return path


def keyframes(name, loop, stops):
    """stops: (seconds, css, timing function for the segment that starts here)."""
    frames = []
    for t, css, timing in stops:
        pct = min(max(t / loop * 100, 0), 100)
        timing = f"animation-timing-function:{timing};" if timing else ""
        frames.append(f"{pct:.3f}%{{{css};{timing}}}")
    return f"@keyframes {name}{{{''.join(frames)}}}"


def image_uri(path, size=None, w=None, fmt=None, quality=86):
    im = Image.open(path)
    if fmt is None:  # keep transparency where there is some
        fmt = "PNG" if im.mode in ("RGBA", "LA", "P") and im.convert("RGBA").getextrema()[3][0] < 255 else "JPEG"
    im = im.convert("RGB" if fmt == "JPEG" else "RGBA")
    if size:
        im = im.resize((size, size), Image.LANCZOS)
    if w:
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    else:
        im.save(buf, "PNG", optimize=True)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def brand_icon(slug, x, y, size, fill):
    d = re.search(r' d="([^"]+)"', (TOOLS / "si" / f"{slug}.svg").read_text()).group(1)
    return f'<path transform="translate({x:.1f} {y:.1f}) scale({size / 24:.4f})" d="{d}" fill="{fill}"/>'


def check_mark(x, y, size, color, stroke=2.4):
    s = size / 16
    return (f'<path transform="translate({x:.1f} {y:.1f}) scale({s:.3f})" d="M2.5 8.6l3.6 3.6L13.6 4.4" '
            f'fill="none" stroke="{color}" stroke-width="{stroke / s:.2f}" stroke-linecap="round" stroke-linejoin="round"/>')


def arrow(x, y, size, color, stroke=2.2):
    s = size / 16
    return (f'<path transform="translate({x:.1f} {y:.1f}) scale({s:.3f})" d="M2 8h11.5M9 3.5L13.5 8 9 12.5" '
            f'fill="none" stroke="{color}" stroke-width="{stroke / s:.2f}" stroke-linecap="round" stroke-linejoin="round"/>')


def rolling_number(svg, x, y, value, key, size, fill, delay, name):
    """Digits roll up like a slot machine once, then stay. Returns the width."""
    digit_w = max(width(key, d, size) for d in "0123456789")
    lh = size * 1.2
    cx = x
    for i, ch in enumerate(value):
        if not ch.isdigit():
            svg << svg.text(cx, y, ch, key, size, fill)
            cx += width(key, ch, size)
            continue
        steps = 10 + int(ch)
        clip = f"{name}c{i}"
        svg.defs.append(f'<clipPath id="{clip}"><rect x="{cx:.1f}" y="{y - size:.1f}" width="{digit_w:.1f}" height="{size * 1.25:.1f}"/></clipPath>')
        glyphs = "".join(svg.text(cx + digit_w / 2, y + k * lh, str(k % 10), key, size, fill, anchor="middle")
                         for k in range(steps + 1))
        svg << f'<g clip-path="url(#{clip})"><g class="{name}{i}">{glyphs}</g></g>'
        svg.css.append(f".{name}{i}{{animation:{name}{i} {1.5 + 0.18 * i:.2f}s cubic-bezier(.16,1,.3,1) {delay:.2f}s both}}"
                       f"@keyframes {name}{i}{{from{{transform:translateY(0)}}to{{transform:translateY(-{steps * lh:.1f}px)}}}}")
        cx += digit_w
    return cx - x


# --------------------------------------------------------------------------- content

APPS = [
    # slug, tile name, line, platforms, link
    ("optiontick", "OptionTick", "Live option-chain charts", "ia", "https://apps.apple.com/in/app/optiontick-nifty-option-chain/id6774950701"),
    ("paiwat", "Paiwat", "Trek planner for Maharashtra", "ia", "https://apps.apple.com/in/app/paiwat/id6749856711"),
    ("mantra-japa", "Mantra Japa", "Mala counter and meditation", "ia", "https://apps.apple.com/in/app/mantra-japa-sadhana/id6760542141"),
    ("devagatha", "Devagatha", "300+ mythic audio stories", "ia", "https://apps.apple.com/in/app/devagatha-mythic-audio-tales/id6761481906"),
    ("inkstroke-table-tennis", "Inkstroke: Table Tennis", "Ping pong, painted in ink", "ia", "https://apps.apple.com/in/app/inkstroke-table-tennis/id6795942890"),
    ("arjun", "Arjun: One Perfect Shot", "Chain-reaction archery", "ia", "https://apps.apple.com/in/app/arjun-one-perfect-shot/id6810334577"),
    ("inkstroke-badminton", "Inkstroke: Badminton", "Badminton, painted in ink", "a", "https://play.google.com/store/apps/details?id=com.aniketnagapure.inkstrokebadminton"),
    ("stack-and-smash", "Stack & Smash", "Stack, dodge and smash", "a", "https://play.google.com/store/apps/details?id=com.nanket.stackandsmash"),
    ("swami-vivekananda", "Swami Vivekananda", "Quotes, books and audio", "ia", "https://apps.apple.com/in/app/teachings-of-swami-vivekananda/id6751097934"),
    ("chhatrapati-swarajya", "Chhatrapati Swarajya", "Audio stories of Swarajya", "i", "https://apps.apple.com/in/app/chhatrapati-swarajya/id6764873284"),
    ("byteprep", "BytePrep", "Interview prep, 25+ stacks", "ia", "https://apps.apple.com/in/app/byte-prep/id6751103244"),
    ("marathi-bol", "Marathi Bol", "Learn to speak Marathi", "a", "https://play.google.com/store/apps/details?id=com.ninjaaniket.marathiduolingo"),
]
MORE_APPS = [
    ("ExpenseAI", "https://play.google.com/store/apps/details?id=com.ninjaaniket.AIExpenseTracker"),
    ("Hind-Kahaniya", "https://play.google.com/store/apps/details?id=com.indian.hindi.audio.stories"),
    ("21 Day Memory", "https://play.google.com/store/apps/details?id=com.antigravity.memory"),
]
APP_COUNT = len(APPS) + len(MORE_APPS) + 1  # + Breeze

LINKS = {
    "site": "https://www.aniketnagapure.dev",
    "linkedin": "https://linkedin.com/in/aniket-nagapure",
    "x": "https://x.com/aniketvnagapure",
    "email": "mailto:nanket.dev@gmail.com",
    "youtube": "https://www.youtube.com/@interviewarcade",
    "breeze": "https://github.com/nanket/breeze",
    "breeze_download": "https://nanket.github.io/breeze/",
    "ai_scratch": "https://github.com/nanket/ai-engineering-from-scratch",
}

INK, CREAM, MUTED, SOFT = "#0B0C10", "#F4EFE6", "#8F95A0", "#ABB0BA"
ORANGE, GREEN, BLUE = "#FF7A1A", "#3EE6A0", "#86B8FF"

THEMES = {
    "dark": dict(text="#F0F6FC", muted="#9198A1", card="#151B23", line="#2A313C", accent="#FF8A3D",
                 mono_icon="#F0F6FC", shadow=0.55, sheen=0.22),
    "light": dict(text="#1F2328", muted="#59636E", card="#FFFFFF", line="#E4DFD7", accent="#E0600A",
                  mono_icon="#1F2328", shadow=0.16, sheen=0.35),
}


# --------------------------------------------------------------------------- hero

def hero():
    W, H = 1200, 700
    s = SVG(W, H, f"Aniket Nagapure, Senior Product Engineer in Mumbai. I build apps and ship them: "
                  f"{APP_COUNT} apps shipped, 382 GB freed by Breeze, 1K+ YouTube subscribers.")
    s.defs += [
        f'<clipPath id="frame"><rect width="{W}" height="{H}" rx="28"/></clipPath>',
        '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.3" fill="#1D2029"/></pattern>',
        f'<radialGradient id="glow" cx="0.86" cy="0.02" r="0.75"><stop offset="0" stop-color="{ORANGE}" stop-opacity="0.24"/>'
        f'<stop offset="1" stop-color="{ORANGE}" stop-opacity="0"/></radialGradient>',
        '<filter id="lift" x="-25%" y="-25%" width="150%" height="170%"><feDropShadow dx="0" dy="24" stdDeviation="24" flood-color="#000" flood-opacity="0.6"/></filter>',
    ]
    s << '<g clip-path="url(#frame)">'
    s << f'<rect width="{W}" height="{H}" fill="{INK}"/><rect width="{W}" height="{H}" fill="url(#dots)"/><rect width="{W}" height="{H}" fill="url(#glow)"/>'

    # Menu bar.
    s << '<rect width="1200" height="44" fill="#FFFFFF" fill-opacity="0.035"/><rect y="44" width="1200" height="1" fill="#FFFFFF" fill-opacity="0.07"/>'
    s << f'<circle cx="36" cy="22" r="7" fill="{ORANGE}"/>'
    s << s.text(54, 27.5, "aniket", "ui6", 15, CREAM)
    x = 54 + width("ui6", "aniket", 15) + 30
    for item in ["Apps", "Open Source", "Games", "YouTube"]:
        s << s.text(x, 27.5, item, "ui", 15, SOFT)
        x += width("ui", item, 15) + 26
    where = "Mumbai · IST"
    s << s.text(1172, 27.5, where, "ui", 14, MUTED, anchor="end")
    sx = 1172 - width("ui", where, 14) - 26
    s << s.text(sx, 27.5, "Shipping", "ui6", 14, CREAM, anchor="end")
    dx = sx - width("ui6", "Shipping", 14) - 12
    s << f'<circle class="pulse" cx="{dx:.1f}" cy="22.5" r="4" fill="{GREEN}"/><circle cx="{dx:.1f}" cy="22.5" r="4" fill="{GREEN}"/>'
    s.css.append(".pulse{transform-box:fill-box;transform-origin:center;animation:pulse 2.2s ease-out infinite}"
                 "@keyframes pulse{0%{transform:scale(1);opacity:.8}100%{transform:scale(3.4);opacity:0}}")

    # Headline.
    s << s.text(64, 124, "SENIOR PRODUCT ENGINEER · MUMBAI", "mono7", 14, ORANGE, ls=2.6)
    size = 80
    s << s.text(62, 214, "I build apps", "display", size, CREAM)
    x = 62
    s << s.text(x, 304, "and ", "display", size, CREAM)
    x += width("display", "and ", size)
    ship_w = width("serif", "ship", size * 1.24)
    s << s.text(x, 304, "ship", "serif", size * 1.24, ORANGE)
    # A hand-drawn ink stroke under "ship".
    x0, x1, yy = x + 2, x + ship_w - 4, 322
    s << (f'<path class="ink" d="M{x0:.1f} {yy + 4} C {x0 + ship_w * .25:.1f} {yy - 6}, {x0 + ship_w * .55:.1f} {yy + 9}, {x1:.1f} {yy - 2}" '
          f'fill="none" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round" pathLength="100"/>')
    s.css.append(".ink{stroke-dasharray:100;animation:ink 1s cubic-bezier(.6,0,.2,1) .7s both}@keyframes ink{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}")
    x += ship_w + 12  # the italic p overhangs its advance
    s << s.text(x, 304, " them.", "display", size, CREAM)

    body = [f"{APP_COUNT} apps live on the App Store, Google Play and",
            "macOS: trading tools, trek guides, ink-drawn games",
            "and an open-source Mac cleaner."]
    for i, line in enumerate(body):
        s << s.text(64, 364 + i * 31, line, "ui", 20, SOFT)

    # Stats that roll up once.
    stats = [(str(APP_COUNT), "apps shipped"), ("382 GB", "freed by Breeze"), ("1K+", "YouTube subscribers")]
    x = 64
    for i, (num, label) in enumerate(stats):
        w = rolling_number(s, x, 494, num, "display", 44, CREAM, 0.6 + 0.2 * i, f"st{i}")
        s << s.text(x, 520, label, "ui", 14, MUTED)
        x += max(w, width("ui", label, 14)) + 46
        if i < len(stats) - 1:
            s << f'<rect x="{x - 24:.1f}" y="458" width="1" height="68" fill="#FFFFFF" fill-opacity="0.09"/>'

    terminal(s)
    dock(s)
    s << "</g>"
    s << f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="27.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.08"/>'
    return s.save("hero")


def terminal(s):
    TX, TY, TW, TH, LOOP = 632, 92, 512, 372, 20.0
    BG = "#101218"
    s.defs.append(f'<clipPath id="term"><rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="14"/></clipPath>')
    # Shadow on its own layer: a filtered fill renders a shade off, and the typing covers must match it exactly.
    s << f'<rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="14" fill="{BG}" filter="url(#lift)"/>'
    s << f'<rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="14" fill="{BG}"/>'
    s << f'<g clip-path="url(#term)"><rect x="{TX}" y="{TY}" width="{TW}" height="38" fill="#181B22"/><rect x="{TX}" y="{TY + 38}" width="{TW}" height="1" fill="#FFFFFF" fill-opacity="0.06"/></g>'
    for i, c in enumerate(["#FF5F57", "#FEBC2E", "#28C840"]):
        s << f'<circle cx="{TX + 22 + i * 20}" cy="{TY + 19}" r="6.5" fill="{c}"/>'
    s << s.text(TX + TW / 2, TY + 24, "aniket — zsh — 80×24", "mono", 13, MUTED, anchor="middle")

    FS, LH = 16, 29
    cw = width("mono", "0", FS)
    x0, y0 = TX + 24, TY + 38 + 36
    prompt = "~ %"
    pw = width("mono7", prompt + " ", FS)
    lines = [
        ("cmd", 0.4, "whoami"),
        ("out", 1.3, "aniket · senior product engineer, mumbai", "#C9CDD5", "mono"),
        ("cmd", 2.1, "ls ~/shipped"),
        ("out", 3.2, "breeze  optiontick  paiwat  mantra-japa", BLUE, "mono"),
        ("out", 3.32, "devagatha  arjun  inkstroke  byteprep", BLUE, "mono"),
        ("out", 3.44, f"stack-and-smash  marathi-bol  +{APP_COUNT - 10} more", BLUE, "mono"),
        ("cmd", 4.3, "breeze clean ~/Developer"),
        ("out", 6.4, "scanning node_modules, DerivedData, Pods…", MUTED, "mono"),
        ("ok", 8.0, "382.25 GB freed. Nothing important touched.", GREEN, "mono7"),
        ("end", 8.5),
    ]
    s << f'<g class="tc" clip-path="url(#term)">'
    s.css.append(".tc{animation:tc %ss linear infinite}" % LOOP + keyframes("tc", LOOP, [
        (0, "opacity:1", None), (LOOP - 1.2, "opacity:1", None), (LOOP - 0.6, "opacity:0", None), (LOOP, "opacity:0", None)]))
    for i, spec in enumerate(lines):
        kind, t = spec[0], spec[1]
        y = y0 + i * LH
        cls = f"t{i}"
        s.css.append(f".{cls}{{animation:{cls} {LOOP}s linear infinite}}" + keyframes(cls, LOOP, [
            (0, "opacity:0", None), (t, "opacity:0", "steps(1,end)"), (t + 0.01, "opacity:1", None), (LOOP, "opacity:1", None)]))
        if kind in ("cmd", "end"):
            s << f'<g class="{cls}">' + s.text(x0, y, prompt, "mono7", FS, ORANGE)
            if kind == "end":
                s << f'<rect class="blink" x="{x0 + pw:.1f}" y="{y - FS + 2}" width="{cw:.1f}" height="{FS + 3}" fill="{CREAM}"/></g>'
                s.css.append(".blink{animation:blink 1.05s steps(1,end) infinite}@keyframes blink{0%{opacity:1}50%{opacity:0}}")
                continue
            cmd = spec[2]
            s << s.text(x0 + pw, y, cmd, "mono", FS, CREAM) + "</g>"
            # A cover in the terminal colour slides right a character at a time, with a cursor on its edge.
            n, start = len(cmd), t + 0.3
            end = start + n * 0.075
            cover = f"k{i}"
            s << (f'<g class="{cover}"><rect x="{x0 + pw:.1f}" y="{y - FS - 2}" width="{n * cw + 2 * cw:.1f}" height="{LH}" fill="{BG}"/>'
                  f'<rect class="{cover}c" x="{x0 + pw:.1f}" y="{y - FS + 2}" width="{cw:.1f}" height="{FS + 3}" fill="{CREAM}"/></g>')
            s.css.append(f".{cover}{{animation:{cover} {LOOP}s linear infinite}}" + keyframes(cover, LOOP, [
                (0, "transform:translateX(0)", None), (start, "transform:translateX(0)", f"steps({n},end)"),
                (end, f"transform:translateX({n * cw:.2f}px)", None), (LOOP, f"transform:translateX({n * cw:.2f}px)", None)]))
            s.css.append(f".{cover}c{{animation:{cover}c {LOOP}s linear infinite}}" + keyframes(f"{cover}c", LOOP, [
                (0, "opacity:0", None), (t, "opacity:0", "steps(1,end)"), (t + 0.01, "opacity:1", None),
                (end + 0.25, "opacity:1", "steps(1,end)"), (end + 0.26, "opacity:0", None), (LOOP, "opacity:0", None)]))
        elif kind == "ok":
            s << f'<g class="{cls}">' + check_mark(x0 - 1, y - FS + 2, FS, GREEN, 2.6) + s.text(x0 + 2 * cw, y, spec[2], spec[4], FS, spec[3]) + "</g>"
        else:
            s << f'<g class="{cls}">' + s.text(x0, y, spec[2], spec[4], FS, spec[3]) + "</g>"
    s << "</g>"
    s << f'<rect x="{TX + .5}" y="{TY + .5}" width="{TW - 1}" height="{TH - 1}" rx="13.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.1"/>'


def dock(s):
    items = [("Breeze", TOOLS / "brand" / "breeze-icon.png")] + [(a[1].split(":")[0], TOOLS / "icons" / icon_file(a[0])) for a in APPS]
    n, size, gap, pad, LOOP = len(items), 52, 16, 20, 17.0
    dw = n * size + (n - 1) * gap + 2 * pad
    dx, dy, dh = (1200 - dw) / 2, 598, size + 28
    s << f'<rect x="{dx:.1f}" y="{dy}" width="{dw:.1f}" height="{dh}" rx="22" fill="#FFFFFF" fill-opacity="0.06" stroke="#FFFFFF" stroke-opacity="0.1"/>'
    for i, (name, path) in enumerate(items):
        x, y = dx + pad + i * (size + gap), dy + 14
        t = 0.8 + i * 1.2
        s.defs.append(f'<clipPath id="dk{i}"><rect x="{x:.1f}" y="{y}" width="{size}" height="{size}" rx="12.5"/></clipPath>')
        s << (f'<g class="b{i}"><image href="{image_uri(path, size=112)}" x="{x:.1f}" y="{y}" width="{size}" height="{size}" '
              f'clip-path="url(#dk{i})"/></g>')
        s << f'<circle cx="{x + size / 2:.1f}" cy="{dy + dh - 6}" r="2" fill="{CREAM}" fill-opacity="0.5"/>'
        s.css.append(f".b{i}{{animation:b{i} {LOOP}s linear infinite}}" + keyframes(f"b{i}", LOOP, [
            (0, "transform:translateY(0)", None), (t, "transform:translateY(0)", "cubic-bezier(.2,.7,.3,1)"),
            (t + 0.24, "transform:translateY(-20px)", "cubic-bezier(.6,0,.8,.3)"), (t + 0.48, "transform:translateY(0)", "cubic-bezier(.2,.7,.3,1)"),
            (t + 0.64, "transform:translateY(-8px)", "cubic-bezier(.6,0,.8,.3)"), (t + 0.8, "transform:translateY(0)", None),
            (LOOP, "transform:translateY(0)", None)]))
        # The app's name floats above it while it bounces, like the real Dock.
        lw = width("ui6", name, 13) + 22
        lx, ly = x + size / 2 - lw / 2, dy - 38
        s << (f'<g class="n{i}"><rect x="{lx:.1f}" y="{ly}" width="{lw:.1f}" height="28" rx="8" fill="#1E222B" stroke="#FFFFFF" stroke-opacity="0.12"/>'
              + s.text(x + size / 2, ly + 18.5, name, "ui6", 13, CREAM, anchor="middle") + "</g>")
        s.css.append(f".n{i}{{animation:n{i} {LOOP}s linear infinite}}" + keyframes(f"n{i}", LOOP, [
            (0, "opacity:0", None), (t, "opacity:0", "ease-out"), (t + 0.2, "opacity:1", None),
            (t + 1.15, "opacity:1", "ease-in"), (t + 1.35, "opacity:0", None), (LOOP, "opacity:0", None)]))


def icon_file(slug):
    for ext in (".jpg", ".png"):
        if (TOOLS / "icons" / f"{slug}{ext}").exists():
            return f"{slug}{ext}"
    raise FileNotFoundError(slug)


# --------------------------------------------------------------------------- breeze

def breeze_card():
    W, H = 1200, 620
    BASE, VIOLET, MINT = "#0C0A1C", "#8B7CFF", "#3EE6C4"
    s = SVG(W, H, "Breeze: a free, open-source Mac cleaner for developers. Clears node_modules, Xcode "
                  "DerivedData and developer caches, uninstalls apps with their leftovers, and deletes "
                  "nothing until you review it. 382.25 GB freed on my own Mac.")
    s.defs += [
        f'<clipPath id="frame"><rect width="{W}" height="{H}" rx="28"/></clipPath>',
        '<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="70"/></filter>',
        '<filter id="lift" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="26" stdDeviation="26" flood-color="#000" flood-opacity="0.6"/></filter>',
        '<linearGradient id="sheen" x1="0" x2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/>'
        '<stop offset="0.5" stop-color="#FFFFFF" stop-opacity="0.16"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>',
        f'<linearGradient id="brand" x1="0" x2="1"><stop offset="0" stop-color="{VIOLET}"/><stop offset="1" stop-color="{MINT}"/></linearGradient>',
    ]
    s << '<g clip-path="url(#frame)">'
    s << f'<rect width="{W}" height="{H}" fill="{BASE}"/>'
    s << f'<circle cx="1080" cy="40" r="300" fill="{VIOLET}" fill-opacity="0.35" filter="url(#blur)"/>'
    s << f'<circle cx="560" cy="660" r="260" fill="{MINT}" fill-opacity="0.16" filter="url(#blur)"/>'

    s.defs.append('<clipPath id="icon"><rect x="64" y="60" width="104" height="104" rx="24"/></clipPath>')
    s << f'<image href="{image_uri(TOOLS / "brand" / "breeze-icon.png", size=208)}" x="64" y="60" width="104" height="104" clip-path="url(#icon)" filter="url(#lift)"/>'
    s << s.text(64, 216, "NOW SHIPPING · v1.4 · FREE & OPEN SOURCE", "mono7", 14, MINT, ls=2.2)
    s << s.text(60, 300, "Breeze", "display", 86, CREAM)
    s << s.text(64, 346, "The Mac cleaner I wanted as a developer.", "ui", 22, "#CFCAEB")
    bullets = ["Clears node_modules, DerivedData and dev caches",
               "Uninstalls apps along with their leftovers",
               "Deletes nothing until you have reviewed it"]
    for i, b in enumerate(bullets):
        y = 404 + i * 36
        s << f'<circle cx="75" cy="{y - 6}" r="11" fill="{MINT}" fill-opacity="0.14"/>' + check_mark(67, y - 14, 16, MINT, 2.4)
        s << s.text(98, y, b, "ui", 18, "#E9E6F7")
    x = 64
    for chip in ["SwiftUI", "macOS 14+", "Signed & notarized", "GPL-3.0"]:
        w = width("ui6", chip, 15) + 28
        s << f'<rect x="{x}" y="518" width="{w:.1f}" height="34" rx="17" fill="#FFFFFF" fill-opacity="0.06" stroke="#FFFFFF" stroke-opacity="0.16"/>'
        s << s.text(x + w / 2, 540, chip, "ui6", 15, "#DCD8F0", anchor="middle")
        x += w + 10

    # The real app, with a light sweeping across it now and then.
    SX, SY, SW = 600, 96, 556
    SH = SW * 780 / 1200
    s.defs.append(f'<clipPath id="shot"><rect x="{SX}" y="{SY}" width="{SW}" height="{SH:.1f}" rx="14"/></clipPath>')
    s << f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH:.1f}" rx="14" fill="{BASE}" filter="url(#lift)"/>'
    s << f'<image href="{image_uri(TOOLS / "brand" / "breeze-scan.jpg", w=1112, quality=82)}" x="{SX}" y="{SY}" width="{SW}" height="{SH:.1f}" clip-path="url(#shot)"/>'
    s << f'<g clip-path="url(#shot)"><rect class="sheen" x="{SX - 260}" y="{SY - 40}" width="180" height="{SH + 80:.1f}" fill="url(#sheen)" transform="skewX(-18)"/></g>'
    s.css.append(".sheen{animation:sheen 7s ease-in-out 1.5s infinite}" + keyframes("sheen", 7, [
        (0, "transform:skewX(-18deg) translateX(0)", None), (1.4, "transform:skewX(-18deg) translateX(1000px)", None),
        (7, "transform:skewX(-18deg) translateX(1000px)", None)]))
    s << f'<rect x="{SX + .5}" y="{SY + .5}" width="{SW - 1}" height="{SH - 1:.1f}" rx="13.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.14"/>'

    # The headline number, in a floating badge over the screenshot.
    bx, by, bw, bh = 560, 410, 300, 104
    s << f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="22" fill="#141130" fill-opacity="0.94" stroke="url(#brand)" stroke-width="1.5" filter="url(#lift)"/>'
    w = rolling_number(s, bx + 26, by + 58, "382.25", "display", 44, MINT, 0.5, "gb")
    s << s.text(bx + 26 + w + 10, by + 58, "GB", "display", 26, MINT)
    s << s.text(bx + 26, by + 84, "freed on my own Mac so far", "ui", 15, "#B9B3DA")
    s << "</g>"
    s << f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="27.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.1"/>'
    return s.save("breeze")


def buttons():
    # Download: the same in both themes.
    label = "Download for macOS"
    w = 56 + 22 + 12 + width("ui6", label, 22) + 30
    s = SVG(round(w), 72, "Download Breeze for macOS")
    s.defs.append('<linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#8B7CFF"/><stop offset="1" stop-color="#3EE6C4"/></linearGradient>')
    s << f'<rect x="1" y="1" width="{w - 2:.1f}" height="70" rx="35" fill="url(#g)"/>'
    s << ('<path transform="translate(30 22) scale(1.6)" d="M8 1.5v9M4 7l4 4 4-4M2 14h12" fill="none" stroke="#0C0A1C" '
          'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>')
    s << s.text(68, 44, label, "ui6", 22, "#0C0A1C")
    s.save("btn-download")
    for theme, c in THEMES.items():
        label = "Read the source"
        w = 30 + 26 + 12 + width("ui6", label, 22) + 30
        s = SVG(round(w), 72, "Read Breeze's source code on GitHub")
        s << f'<rect x="1" y="1" width="{w - 2:.1f}" height="70" rx="35" fill="{c["card"]}" stroke="{c["line"]}" stroke-width="1.5"/>'
        s << brand_icon("github", 30, 23, 26, c["text"])
        s << s.text(68, 44, label, "ui6", 22, c["text"])
        s.save(f"btn-source-{theme}")


# --------------------------------------------------------------------------- themed pieces

HEADERS = [
    ("01", "NOW SHIPPING", "A Mac cleaner, free and open source"),
    ("02", "THE SHELF", f"{APP_COUNT} apps, live in the stores"),
    ("03", "ON YOUTUBE", "I teach this stuff too"),
    ("04", "TOOLBOX", "What I build with"),
    ("05", "COMMIT LOG", "A year of commits, eaten by a snake"),
    ("06", "SAY HI", "Let's build something"),
]


def header(num, label, title):
    for theme, c in THEMES.items():
        s = SVG(1200, 112, f"{label.title()}: {title}")
        tag = f"{num} / {label}"
        s << s.text(2, 34, tag, "mono7", 15, c["accent"], ls=3)
        lx = 2 + width("mono7", tag, 15, 3) + 20
        s << f'<path class="rule" d="M{lx:.1f} 29.5H1198" stroke="{c["accent"]}" stroke-opacity="0.4" stroke-width="1.5" pathLength="100"/>'
        s.css.append(".rule{stroke-dasharray:100;animation:rule 1.4s cubic-bezier(.6,0,.2,1) .2s both}"
                     "@keyframes rule{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}")
        s << s.text(0, 96, title, "display", 46, c["text"])
        s.save(f"header-{num}-{theme}")


def app_tiles():
    for idx, (slug, name, line, platforms, _) in enumerate(APPS):
        uri = image_uri(TOOLS / "icons" / icon_file(slug), size=300)
        for theme, c in THEMES.items():
            W, H = 280, 354  # the card is 340 tall; the rest is breathing room between rows
            s = SVG(W, H, f"{name}: {line}")
            s.defs += [
                '<clipPath id="ic"><rect x="66" y="30" width="148" height="148" rx="34"/></clipPath>',
                f'<filter id="sh" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="12" stdDeviation="12" flood-color="#000" flood-opacity="{c["shadow"]}"/></filter>',
                f'<linearGradient id="sheen" x1="0" x2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/>'
                f'<stop offset="0.5" stop-color="#FFFFFF" stop-opacity="{c["sheen"]}"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>',
            ]
            s << f'<rect x=".75" y=".75" width="{W - 1.5}" height="338.5" rx="26" fill="{c["card"]}" stroke="{c["line"]}" stroke-width="1.5"/>'
            s << f'<rect x="66" y="30" width="148" height="148" rx="34" fill="{c["card"]}" filter="url(#sh)"/>'
            s << f'<image href="{uri}" x="66" y="30" width="148" height="148" clip-path="url(#ic)"/>'
            s << f'<rect x="66" y="30" width="148" height="148" rx="34" fill="none" stroke="#000" stroke-opacity="0.08"/>'
            s << '<g clip-path="url(#ic)"><rect class="sheen" x="-60" y="10" width="70" height="200" fill="url(#sheen)"/></g>'
            delay = (idx % 4) * 0.35 + (idx // 4) * 0.5 + 1
            s.css.append(f".sheen{{animation:sheen 9s ease-in-out {delay:.2f}s infinite}}" + keyframes("sheen", 9, [
                (0, "transform:skewX(-20deg) translateX(0)", None), (1.1, "transform:skewX(-20deg) translateX(440px)", None),
                (9, "transform:skewX(-20deg) translateX(440px)", None)]))
            size = min(22, 22 * 248 / width("ui6", name, 22))
            s << s.text(W / 2, 220, name, "ui6", round(size, 1), c["text"], anchor="middle")
            s << s.text(W / 2, 249, line, "ui", 16, c["muted"], anchor="middle")
            # Platform marks along the bottom.
            marks = [("apple", "iOS")] * ("i" in platforms) + [("android", "Android")] * ("a" in platforms)
            parts, total = [], 0
            for icon, label in marks:
                w = 17 + 6 + width("ui6", label, 14)
                parts.append((icon, label, w))
                total += w
            total += 18 * (len(parts) - 1)
            x = W / 2 - total / 2
            for icon, label, w in parts:
                s << brand_icon(icon, x, 296, 17, c["muted"])
                s << s.text(x + 23, 309, label, "ui6", 14, c["muted"])
                x += w + 18
            s.save(f"apps/{slug}-{theme}")


TOOLBOX = [
    ("WEB", [("react", "React", "#61DAFB", "#149ECA"), ("nextdotjs", "Next.js", None, None), ("typescript", "TypeScript", "#3178C6", "#3178C6"),
             ("nodedotjs", "Node.js", "#5FA04E", "#5FA04E"), ("tailwindcss", "Tailwind CSS", "#38BDF8", "#0EA5E9")]),
    ("MOBILE · MAC", [("react", "React Native", "#61DAFB", "#149ECA"), ("flutter", "Flutter", "#54C5F8", "#0468D7"),
                      ("swift", "Swift & SwiftUI", "#F05138", "#F05138")]),
    ("GAMES · 3D", [("godotengine", "Godot", "#478CBF", "#478CBF"), ("unity", "Unity", None, None),
                    ("blender", "Blender", "#E87D0D", "#E87D0D"), ("threedotjs", "Three.js", None, None)]),
    ("AI · CLOUD", [("python", "Python", "#5A9FD4", "#3776AB"), ("claude", "LLM APIs", "#D97757", "#D97757"),
                    ("supabase", "Supabase", "#3FCF8E", "#2DA56E"), ("firebase", "Firebase", "#FFCA28", "#F29900"),
                    ("cloudflare", "Cloudflare", "#F38020", "#F38020"), ("vercel", "Vercel", None, None)]),
]


def toolbox():
    LOOP = 14.0
    chips = sum(len(r[1]) for r in TOOLBOX)
    for theme, c in THEMES.items():
        s = SVG(1200, len(TOOLBOX) * 74 - 14, "Toolbox: " + "; ".join(
            f"{label.title()}: " + ", ".join(t[1] for t in items) for label, items in TOOLBOX))
        k = 0
        for r, (label, items) in enumerate(TOOLBOX):
            y = r * 74
            s << s.text(2, y + 31, label, "mono7", 14, c["accent"], ls=2.4)
            x = 196
            for slug, name, dark, light in items:
                color = (dark if theme == "dark" else light) or c["mono_icon"]
                w = 16 + 22 + 11 + width("ui6", name, 18) + 18
                s << f'<rect x="{x:.1f}" y="{y + .75}" width="{w:.1f}" height="50" rx="14" fill="{c["card"]}" stroke="{c["line"]}" stroke-width="1.5"/>'
                s << f'<rect class="h{k}" x="{x:.1f}" y="{y + .75}" width="{w:.1f}" height="50" rx="14" fill="none" stroke="{c["accent"]}" stroke-width="1.8"/>'
                t = 0.6 + k * (LOOP - 2) / chips
                s.css.append(f".h{k}{{animation:h{k} {LOOP}s linear infinite}}" + keyframes(f"h{k}", LOOP, [
                    (0, "opacity:0", None), (t, "opacity:0", "ease-out"), (t + 0.25, "opacity:1", None),
                    (t + 0.9, "opacity:1", "ease-in"), (t + 1.6, "opacity:0", None), (LOOP, "opacity:0", None)]))
                s << brand_icon(slug, x + 16, y + 14.5, 22, color)
                s << s.text(x + 49, y + 32, name, "ui6", 18, c["text"])
                x += w + 12
                k += 1
        s.save(f"toolbox-{theme}")


def youtube_card():
    W, H, RED = 1200, 270, "#FF3B3B"
    s = SVG(W, H, "Interview Arcade on YouTube: system design, DSA and AI interviews, animated. 1K+ subscribers.")
    s.defs += [
        f'<clipPath id="frame"><rect width="{W}" height="{H}" rx="28"/></clipPath>',
        f'<radialGradient id="glow" cx="0.92" cy="0.5" r="0.55"><stop offset="0" stop-color="{RED}" stop-opacity="0.26"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>',
        '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.3" fill="#1D2029"/></pattern>',
        '<clipPath id="av"><circle cx="139" cy="135" r="75"/></clipPath>',
    ]
    s << f'<g clip-path="url(#frame)"><rect width="{W}" height="{H}" fill="{INK}"/><rect width="{W}" height="{H}" fill="url(#dots)"/><rect width="{W}" height="{H}" fill="url(#glow)"/>'
    s << f'<circle cx="139" cy="135" r="81" fill="none" stroke="{RED}" stroke-width="3" stroke-opacity="0.85"/>'
    s << f'<image href="{image_uri(TOOLS / "brand" / "ia-avatar.jpg", size=300)}" x="64" y="60" width="150" height="150" clip-path="url(#av)"/>'
    s << s.text(256, 98, "ALSO ON YOUTUBE", "mono7", 14, RED, ls=2.6)
    s << s.text(252, 158, "Interview Arcade", "display", 54, CREAM)
    s << s.text(256, 198, "System design, DSA and AI interviews, animated.", "ui", 21, SOFT)
    s << s.text(256, 230, "1K+ subscribers", "ui6", 16, CREAM)
    # Play button with a slow heartbeat.
    s << (f'<g class="play"><rect x="980" y="88" width="132" height="94" rx="26" fill="{RED}"/>'
          f'<path d="M1034 112 L1066 135 L1034 158 Z" fill="#FFFFFF"/></g>')
    s.css.append(".play{transform-box:fill-box;transform-origin:center;animation:play 2.4s ease-in-out infinite}"
                 "@keyframes play{0%,100%{transform:scale(1)}12%{transform:scale(1.07)}24%{transform:scale(1)}36%{transform:scale(1.04)}48%{transform:scale(1)}}")
    s << s.text(1046, 218, "Watch", "ui6", 16, CREAM, anchor="middle") + arrow(1046 + width("ui6", "Watch", 16) / 2 + 6, 205, 16, CREAM)
    s << "</g>"
    s << f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="27.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.08"/>'
    s.save("youtube")


GLOBE = ('<g transform="translate({x} {y}) scale({s})" fill="none" stroke="{c}" stroke-width="{w}"><circle cx="12" cy="12" r="9.5"/>'
         '<path d="M2.5 12h19M12 2.5c2.6 2.8 3.9 6 3.9 9.5S14.6 18.7 12 21.5C9.4 18.7 8.1 15.5 8.1 12S9.4 5.3 12 2.5z"/></g>')
ENVELOPE = ('<g transform="translate({x} {y}) scale({s})" fill="none" stroke="{c}" stroke-width="{w}" stroke-linejoin="round">'
            '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M3.5 6.5l8.5 6.5 8.5-6.5"/></g>')
CONTACTS = [
    ("site", "aniketnagapure.dev", "globe"),
    ("linkedin", "LinkedIn", "linkedin"),
    ("x", "X", "x"),
    ("email", "Email", "envelope"),
    ("youtube", "YouTube", "youtube"),
]


def contact_buttons():
    for key, label, icon in CONTACTS:
        for theme, c in THEMES.items():
            w = 24 + 24 + 12 + width("ui6", label, 20) + 26
            s = SVG(round(w), 64, label)
            s << f'<rect x="1" y="1" width="{w - 2:.1f}" height="62" rx="31" fill="{c["card"]}" stroke="{c["line"]}" stroke-width="1.5"/>'
            if icon == "globe":
                s << GLOBE.format(x=24, y=20, s=1, c=c["text"], w=1.8)
            elif icon == "envelope":
                s << ENVELOPE.format(x=24, y=20, s=1, c=c["text"], w=1.8)
            else:
                s << brand_icon(icon, 24, 20, 24, "#FF0033" if icon == "youtube" else c["text"])
            s << s.text(60, 39.5, label, "ui6", 20, c["text"])
            s.save(f"contact-{key}-{theme}")


def footer():
    LOOP = 12.0
    lines = [("cmd", 0.5, "exit"), ("out", 1.6, "Thanks for scrolling. Now go clear your node_modules."), ("dim", 2.4, "[Process completed]")]
    FS, LH = 19, 34
    cw = width("mono", "0", FS)
    block = max(width("mono", l[2], FS) for l in lines)
    x0 = (1200 - block) / 2
    for theme, c in THEMES.items():
        s = SVG(1200, 130, "~ % exit. Thanks for scrolling. Now go clear your node_modules.")
        for i, (kind, t, text) in enumerate(lines):
            y = 32 + i * LH
            cls = f"f{i}"
            s.css.append(f".{cls}{{animation:{cls} {LOOP}s linear infinite}}" + keyframes(cls, LOOP, [
                (0, "opacity:0", None), (t, "opacity:0", "steps(1,end)"), (t + 0.01, "opacity:1", None),
                (LOOP - 1, "opacity:1", "ease-in"), (LOOP - 0.4, "opacity:0", None), (LOOP, "opacity:0", None)]))
            if kind == "cmd":
                # Typed a letter at a time: each letter is its own element, so nothing has to match the page colour.
                pw = width("mono7", "~ % ", FS)
                s << f'<g class="{cls}">' + s.text(x0, y, "~ %", "mono7", FS, c["accent"]) + "</g>"
                for k, ch in enumerate(text):
                    lc, at = f"{cls}k{k}", t + 0.35 + k * 0.13
                    s << f'<g class="{lc}">' + s.text(x0 + pw + k * cw, y, ch, "mono", FS, c["text"]) + "</g>"
                    s.css.append(f".{lc}{{animation:{lc} {LOOP}s linear infinite}}" + keyframes(lc, LOOP, [
                        (0, "opacity:0", None), (at, "opacity:0", "steps(1,end)"), (at + 0.01, "opacity:1", None),
                        (LOOP - 1, "opacity:1", "ease-in"), (LOOP - 0.4, "opacity:0", None), (LOOP, "opacity:0", None)]))
            else:
                color = c["text"] if kind == "out" else c["muted"]
                s << f'<g class="{cls}">' + s.text(x0, y, text, "mono" if kind == "dim" else "mono7", FS, color) + "</g>"
        s.save(f"footer-{theme}")


# --------------------------------------------------------------------------- readme

# Absolute URLs: GitHub resolves relative <img src> but not always relative <source srcset>.
RAW = "https://raw.githubusercontent.com/nanket/nanket/main/assets/"


def pic(name, alt, attrs='width="100%"'):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}{name}-dark.svg">'
            f'<img src="{RAW}{name}-light.svg" alt="{escape(alt)}" {attrs}></picture>')


def readme():
    h = {num: pic(f"header-{num}", f"{label.title()}: {title}") for num, label, title in HEADERS}
    tiles = []
    for i, (slug, name, line, _, link) in enumerate(APPS):
        tile = pic("apps/" + slug, f"{name}: {line}", 'width="23%"')
        tiles.append(f'<a href="{link}">{tile}</a>')
    rows = "\n".join(" ".join(tiles[i:i + 4]) + ("<br>" if i + 4 < len(tiles) else "") for i in range(0, len(tiles), 4))
    more = " · ".join(f'<a href="{url}">{name}</a>' for name, url in MORE_APPS)
    contacts = " ".join('<a href="%s">%s</a>' % (LINKS[key], pic(f"contact-{key}", label, 'height="46"')) for key, label, _ in CONTACTS)
    snake = ('<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nanket/nanket/output/snake-dark.svg">'
             '<img src="https://raw.githubusercontent.com/nanket/nanket/output/snake-light.svg" alt="My contribution graph, being eaten by a snake" width="100%"></picture>')
    text = f"""<!-- Generated by tools/build.py: edit the script, not this file. -->

<a href="{LINKS['site']}"><img src="{RAW}hero.svg" width="100%" alt="Aniket Nagapure, Senior Product Engineer in Mumbai. I build apps and ship them: {APP_COUNT} apps shipped, 382 GB freed by Breeze, 1K+ YouTube subscribers."></a>

<br>

{h['01']}

<a href="{LINKS['breeze']}"><img src="{RAW}breeze.svg" width="100%" alt="Breeze: a free, open-source Mac cleaner for developers. It clears node_modules, Xcode DerivedData and developer caches, uninstalls apps with their leftovers, and deletes nothing until you have reviewed it."></a>

<p align="center">
<a href="{LINKS['breeze_download']}"><img src="{RAW}btn-download.svg" height="54" alt="Download Breeze for macOS"></a>&nbsp;&nbsp;<a href="{LINKS['breeze']}">{pic("btn-source", "Read the source", 'height="54"')}</a>
</p>

<br>

{h['02']}

<p align="center">
{rows}
</p>

<p align="center"><sub>Also on Google Play: {more}. And <a href="{LINKS['breeze']}">Breeze</a> on the Mac.</sub></p>

<br>

{h['03']}

<a href="{LINKS['youtube']}"><img src="{RAW}youtube.svg" width="100%" alt="Interview Arcade on YouTube: system design, DSA and AI interviews, animated."></a>

<p align="center"><sub>Code for the series: <a href="{LINKS['ai_scratch']}">AI Engineering from Scratch</a>, from a single neuron to a tiny GPT in plain Python.</sub></p>

<br><br>

{h['04']}

{pic("toolbox", "Toolbox: " + "; ".join(f"{label.title()}: " + ", ".join(t[1] for t in items) for label, items in TOOLBOX))}

<br><br>

{h['05']}

{snake}

<br>

{h['06']}

<p align="center">
{contacts}
</p>

<br>

{pic("footer", "~ % exit. Thanks for scrolling. Now go clear your node_modules.")}
"""
    (ROOT / "README.md").write_text(text)


if __name__ == "__main__":
    hero()
    breeze_card()
    buttons()
    for spec in HEADERS:
        header(*spec)
    app_tiles()
    toolbox()
    youtube_card()
    contact_buttons()
    footer()
    readme()
    for p in sorted(ASSETS.rglob("*.svg")):
        print(f"{p.stat().st_size / 1024:7.1f} KB  {p.relative_to(ROOT)}")
