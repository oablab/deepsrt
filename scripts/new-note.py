#!/usr/bin/env python3
"""Generate a development note in all four locales.

    scripts/new-note.py spec.json [--dry-run]

Every note on this site is the same page in four languages, and doing that by
hand kept going wrong in the same places:

* **Font stacks.** The English page uses a serif for headings ("New York").
  That serif has no CJK coverage, so cloning the English template into zh/ja/ko
  silently drops every heading to whatever the system picks. Three pages shipped
  that way. Each locale's stack is fixed here and asserted after writing.
* **hreflang / og:url / nav** all repeat the slug. Miss one and the locale
  switcher quietly points at the wrong page.
* **`.meta` spacing** is 0.5rem on notes that carry a `.lead`, 0.7rem on notes
  that don't — a detail nobody remembers.
* **Markdown leaks.** Bodies are HTML; a stray `**bold**` renders literally.
  Checked before writing.

Run `--dry-run` first: it validates the spec and reports every file it would
touch without writing anything.
"""

import argparse
import html
import json
import os
import re
import sys
from html.parser import HTMLParser

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SITE, "notes", "why-deepsrt-has-no-servers", "index.html")

# --- per-locale invariants -------------------------------------------------

FONTS = {
    "en": {
        "body": '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif',
        "head": '"New York", Georgia, "Times New Roman", serif',
    },
    # CJK locales use ONE stack for body and headings: there is no CJK serif in
    # the system fonts that pairs with the English display face, and falling
    # back mid-heading looks worse than not using a serif at all.
    "zh": {
        "body": '"PingFang TC", "SF Pro TC", -apple-system, BlinkMacSystemFont, "Heiti TC", "Microsoft JhengHei", sans-serif',
    },
    "ja": {
        "body": '"Hiragino Sans", "Hiragino Kaku Gothic ProN", -apple-system, BlinkMacSystemFont, "Yu Gothic", Meiryo, sans-serif',
    },
    "ko": {
        "body": '"Apple SD Gothic Neo", -apple-system, BlinkMacSystemFont, "Malgun Gothic", "Noto Sans KR", sans-serif',
    },
}
for _loc, _f in FONTS.items():
    _f.setdefault("head", _f["body"])

LOCALES = {
    "en": dict(base="", htmllang="en", back="← Notes", brand="/", label="EN", hreflang="en"),
    "zh": dict(base="/zh", htmllang="zh-Hant", back="← 筆記", brand="/zh/", label="中文", hreflang="zh-Hant"),
    "ja": dict(base="/ja", htmllang="ja", back="← ノート", brand="/ja/", label="日本語", hreflang="ja"),
    "ko": dict(base="/ko", htmllang="ko", back="← 노트", brand="/ko/", label="한국어", hreflang="ko"),
}

# Optional article styling, switched on per spec so unused rules don't ship.
# Styled article links ship on every note: the browser default blue clashes
# with the palette, so links take the theme's deep accent with a quiet
# underline that fills in on hover.
# On a ~375px phone the brand and four locales cannot share a row, and
# mid-string wrapping is the ugliest outcome; stacking matches the homepage.
NAV_RWD_CSS = (
    "    nav .lang { white-space: nowrap; }\n"
    "    @media (max-width: 480px) {\n"
    "      nav { flex-direction: column; gap: 0.35rem; padding: 0.7rem 1rem 0.6rem; }\n"
    "    }\n"
)

LINK_CSS = (
    "    article a { color: var(--accent-deep); text-decoration-color: var(--border); "
    "text-underline-offset: 3px; }\n"
    "    article a:hover { text-decoration-color: var(--accent-deep); }\n"
)

EXTRA_CSS = {
    "lead": '    .lead { font-size: 1.12rem; font-weight: 700; color: var(--muted); margin: 0.9rem 0 0.3rem; line-height: 1.75; }\n',
    "lists": '    article ul { margin: 1rem 0 1rem 1.4rem; }\n    article li { margin: 0.4rem 0; }\n',
    "code": '    article code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92em; background: var(--card); padding: 0.1em 0.35em; border-radius: 5px; }\n',
    "quotes": '    article blockquote { margin: 1.3rem 0; padding: 0.2rem 0 0.2rem 1.1rem; border-left: 3px solid var(--border); color: var(--muted); }\n',
    "figures": (
        '    article figure { margin: 1.6rem 0; }\n'
        '    article figure img { width: 100%; height: auto; border-radius: 12px; border: 1px solid var(--border); display: block; }\n'
        '    article figcaption { color: var(--muted); font-size: 0.88rem; margin-top: 0.6rem; text-align: center; }\n'
    ),
    "tables": (
        '    article .table-wrap { margin: 1.7rem 0; background: var(--card);\n'
        '      border: 1px solid var(--border); border-radius: 16px; overflow-x: auto; }\n'
        '    article table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }\n'
        '    article th { text-align: left; white-space: nowrap; color: var(--muted);\n'
        '      font-weight: 700; font-size: 0.75rem; letter-spacing: 0.07em;\n'
        '      text-transform: uppercase; padding: 1rem 1.1rem 0.55rem; }\n'
        '    article td { text-align: left; vertical-align: top; padding: 0.8rem 1.1rem;\n'
        '      border-top: 1px solid var(--border); }\n'
        '    article td:first-child { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;\n'
        '      font-weight: 700; color: var(--accent-deep); white-space: nowrap; }\n'
        '    article td code { background: none; padding: 0; color: var(--muted); }\n'
    ),
    "callout": (
        '    article .callout { background: var(--accent-tint); border-radius: 14px;\n'
        '      padding: 1.1rem 1.4rem; margin: 1.7rem 0; font-size: 0.98rem; }\n'
    ),
}

REQUIRED_PER_LOCALE = ("title", "desc", "meta", "body")


# --- spec -----------------------------------------------------------------

def load_spec(path):
    with open(path) as f:
        spec = json.load(f)
    slug = spec.get("slug")
    if not slug or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        sys.exit(f"slug must be lowercase-with-hyphens, got {slug!r}")
    missing = [loc for loc in LOCALES if loc not in spec.get("locales", {})]
    if missing:
        sys.exit(f"spec is missing locales: {', '.join(missing)} "
                 "(a note ships in all four or not at all)")
    problems = []
    for loc, cfg in spec["locales"].items():
        if loc not in LOCALES:
            problems.append(f"unknown locale {loc!r}")
            continue
        for field in REQUIRED_PER_LOCALE:
            if not cfg.get(field):
                problems.append(f"{loc}: missing {field}")
        body = cfg.get("body", "")
        if "**" in body:
            problems.append(f"{loc}: body contains '**' — bodies are HTML, "
                            "use <strong> (markdown renders literally)")
        if cfg.get("lead") and "<" in cfg["lead"]:
            problems.append(f"{loc}: lead should be plain text")
    for feature in spec.get("css", []):
        if feature not in EXTRA_CSS:
            problems.append(f"unknown css feature {feature!r}; "
                            f"available: {', '.join(sorted(EXTRA_CSS))}")
    if problems:
        sys.exit("spec problems:\n  - " + "\n  - ".join(problems))
    return spec


# --- page building --------------------------------------------------------

def build_page(loc, spec, template):
    cfg = spec["locales"][loc]
    meta = LOCALES[loc]
    slug = spec["slug"]
    base = meta["base"]
    url = f"https://deepsrt.com{base}/notes/{slug}/"
    card = f"{url}og-card.png"
    esc_title = html.escape(cfg["title"], quote=True)
    esc_desc = html.escape(cfg["desc"], quote=True)
    s = template

    s = s.replace('<html lang="en">', f'<html lang="{meta["htmllang"]}">', 1)
    s = re.sub(r"<title>.*?</title>", f"<title>{esc_title}</title>", s, count=1)
    for prop, value in (("description", esc_desc),):
        s = re.sub(rf'<meta name="{prop}" content=".*?">',
                   f'<meta name="{prop}" content="{value}">', s, count=1)
    for prop, value in (("og:title", esc_title), ("og:description", esc_desc),
                        ("og:url", url), ("og:image", card)):
        s = re.sub(rf'<meta property="{prop}" content=".*?">',
                   f'<meta property="{prop}" content="{value}">', s, count=1)
    s = re.sub(r'<meta name="twitter:image" content=".*?">',
               f'<meta name="twitter:image" content="{card}">', s, count=1)

    alts = "\n".join(
        f'  <link rel="alternate" hreflang="{LOCALES[l]["hreflang"]}" '
        f'href="https://deepsrt.com{LOCALES[l]["base"]}/notes/{slug}/">'
        for l in LOCALES
    ) + f'\n  <link rel="alternate" hreflang="x-default" href="https://deepsrt.com/notes/{slug}/">'
    s = re.sub(r'  <link rel="alternate" hreflang="en".*?x-default" href="[^"]*">',
               alts, s, count=1, flags=re.S)

    # Fonts. THIS is the step that kept getting skipped.
    fonts = FONTS[loc]
    s = re.sub(r"      --font-body: [^\n]*\n", f'      --font-body: {fonts["body"]};\n', s, count=1)
    s = re.sub(r"      --font-head: [^\n]*\n", f'      --font-head: {fonts["head"]};\n', s, count=1)

    has_lead = bool(cfg.get("lead"))
    features = list(spec.get("css", []))
    if has_lead and "lead" not in features:
        features.insert(0, "lead")
    extra = NAV_RWD_CSS + LINK_CSS + "".join(EXTRA_CSS[f] for f in features)
    meta_margin = "0.5rem" if has_lead else "0.7rem"
    s = re.sub(r"    \.meta \{[^\n]*\n",
               f'    .meta {{ color: var(--muted); font-size: 0.92rem; margin: {meta_margin} 0 2.2rem; }}\n'
               + extra, s, count=1)

    langs = "｜".join(
        f'<a href="{LOCALES[l]["base"]}/notes/{slug}/"'
        + (' class="active"' if l == loc else "")
        + f'>{LOCALES[l]["label"]}</a>'
        for l in LOCALES
    )
    s = re.sub(r"<nav>.*?</nav>",
               f'<nav>\n  <a class="brand" href="{meta["brand"]}">'
               f'<img src="/icon.svg" alt=""> DeepSRT</a>\n'
               f'  <span class="lang">{langs}</span>\n</nav>',
               s, count=1, flags=re.S)

    s = re.sub(r'<a class="backlink" href="[^"]*">[^<]*</a>',
               f'<a class="backlink" href="{base}/notes/">{meta["back"]}</a>', s, count=1)
    s = re.sub(r"<h1>.*?</h1>", f'<h1>{cfg["title"]}</h1>', s, count=1, flags=re.S)
    lead_html = f'\n  <p class="lead">{cfg["lead"]}</p>' if has_lead else ""
    s = re.sub(r'<p class="meta">.*?</p>',
               f'<p class="meta">{cfg["meta"]}</p>{lead_html}', s, count=1, flags=re.S)
    s = re.sub(r"<article>.*?</article>",
               "<article>\n" + cfg["body"].strip() + "\n\n  </article>",
               s, count=1, flags=re.S)
    return s


def listing_entry(loc, spec):
    cfg = spec["locales"][loc]
    base = LOCALES[loc]["base"]
    summary = cfg.get("summary") or cfg["desc"]
    return (f'    <li>\n'
            f'      <a href="{base}/notes/{spec["slug"]}/">\n'
            f'        <div class="t">{cfg["title"]}</div>\n'
            f'        <div class="d">{cfg["meta"]}</div>\n'
            f'        <div class="s">{summary}</div>\n'
            f'      </a>\n'
            f'    </li>')


# --- OG cards -------------------------------------------------------------

CARD_FONTS = {
    "en": ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    "zh": ("/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
           "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc", 10),
    "ja": ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 0),
    "ko": ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 6),
}
HELV = "/System/Library/Fonts/HelveticaNeue.ttc"
MENLO = "/System/Library/Fonts/Menlo.ttc"


def write_card(loc, spec, path):
    from PIL import Image, ImageDraw, ImageFont

    cfg = spec["locales"][loc]
    card = cfg.get("card") or {}
    lines = card.get("lines") or [cfg["title"]]
    subtitle = card.get("subtitle", "")
    size = card.get("size", 58 if loc == "en" else 62)
    fpath, fidx = CARD_FONTS[loc]

    def font(p, i, s):
        try:
            return ImageFont.truetype(p, s, index=i)
        except Exception:
            return ImageFont.truetype(HELV, s, index=1)

    W, H = 1200, 630
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=(int(30 + (11 - 30) * t), int(58 + (23 - 58) * t), int(95 + (38 - 95) * t)))
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(wm).text((830, -40), "D", font=font(HELV, 1, 620), fill=(255, 255, 255, 14))
    img = Image.alpha_composite(img.convert("RGBA"), wm).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([72, 64, 156, 148], radius=20, fill=(255, 255, 255))
    d.text((94, 74), "D", font=font(HELV, 1, 72), fill=(29, 94, 140))
    d.text((176, 92), "DeepSRT", font=font(HELV, 1, 42), fill=(255, 255, 255))
    y = 248
    for line in lines:
        d.text((76, y), line, font=font(fpath, fidx, size), fill=(255, 255, 255))
        y += int(size * 1.36)
    if subtitle:
        d.text((76, y + 26), subtitle, font=font(fpath, fidx, 29), fill=(150, 170, 188))
    d.text((76, H - 74), "deepsrt.com", font=font(MENLO, 1, 26), fill=(111, 182, 228))
    img.save(path)
    return os.path.getsize(path)


# --- verification ---------------------------------------------------------

def verify(loc, spec, path):
    s = open(path).read()
    HTMLParser().feed(s)
    problems = []
    expected = FONTS[loc]["head"].split(",")[0].strip()
    if f"--font-head: {FONTS[loc]['head']};" not in s:
        problems.append(f"font-head is not the {loc} stack (expected {expected})")
    if loc != "en" and "New York" in s:
        problems.append("English serif leaked into a CJK page")
    if "**" in s:
        problems.append("markdown '**' survived into the HTML")
    for token in (f"/notes/{spec['slug']}/",):
        if s.count(token) < 5:  # nav x4 + hreflang, at minimum
            problems.append(f"slug {token} appears only {s.count(token)} times")
    if "PLACEHOLDER" in s or "TODO" in s:
        problems.append("placeholder text left in the page")
    return problems


# --- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="JSON spec (see scripts/note-spec.example.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and list files without writing")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    slug = spec["slug"]
    template = open(TEMPLATE).read()

    planned = []
    for loc in LOCALES:
        base = LOCALES[loc]["base"].lstrip("/")
        d = os.path.join(SITE, base, "notes", slug)
        planned.append((loc, d, os.path.join(d, "index.html"),
                        os.path.join(d, "og-card.png"),
                        os.path.join(SITE, base, "notes", "index.html")))

    if args.dry_run:
        print(f"spec OK — {slug}")
        for loc, _, page, card, listing in planned:
            exists = " (OVERWRITES)" if os.path.exists(page) else ""
            print(f"  {loc}: {os.path.relpath(page, SITE)}{exists}")
            print(f"      {os.path.relpath(card, SITE)}")
            print(f"      {os.path.relpath(listing, SITE)} (prepend entry)")
        return

    failures = []
    for loc, d, page, card, listing in planned:
        os.makedirs(d, exist_ok=True)
        with open(page, "w") as f:
            f.write(build_page(loc, spec, template))
        kb = write_card(loc, spec, card) // 1024
        problems = verify(loc, spec, page)
        failures += [f"{loc}: {p}" for p in problems]

        listing_src = open(listing).read()
        anchor = '<ul class="note-list">'
        if f'/notes/{slug}/"' in listing_src:
            print(f"  {loc}: already listed, leaving the index alone")
        elif anchor in listing_src:
            open(listing, "w").write(
                listing_src.replace(anchor, anchor + "\n" + listing_entry(loc, spec), 1))
        else:
            failures.append(f"{loc}: no <ul class=\"note-list\"> in {listing}")
        print(f"  {loc}: wrote page + {kb}KB card"
              + (f" — {len(problems)} PROBLEM(S)" if problems else ""))

    if failures:
        print("\nverification failed:", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)
    print(f"\n{slug} written in {len(planned)} locales, all checks passed.")


if __name__ == "__main__":
    main()
