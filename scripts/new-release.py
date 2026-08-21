#!/usr/bin/env python3
"""Generate deepsrt.com/releases/ in all four locales from releases.json.

Same contract as new-note.py: the data file is the source of truth and the
HTML is disposable output. Four hand-maintained locale files drift — one of
them kept a stale "Latest" badge for two releases before this script existed.

    python3 scripts/new-release.py --check   # verify without writing
    python3 scripts/new-release.py           # write all four locales

Card styling is ported from foldic.app/releases/ (rows as cards, solid
version chip, tinted Latest / outlined In-review / outlined platform pills);
the palette, the serif headings and the four-file + hreflang structure stay
DeepSRT's.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "releases.json"

# Exactly one row may claim to be the latest shipping version; "review" is a
# promise rather than a fact, so it does not count as one.
STATUSES = {None, "latest", "review"}

CSS = """\
    :root {
      --accent: #4E9FD1; --accent-deep: #1D5E8C; --accent-tint: #DCEDF7;
      --ink: #1B2C3A; --muted: #5C7386; --bg: #F2F7FA; --card: #E6EFF5;
      --border: rgba(29, 94, 140, 0.16);
      --font-body: __FONT_BODY__;
      --font-head: __FONT_HEAD__;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --accent: #6FB6E4; --accent-deep: #A8D4EF; --accent-tint: #16242E;
        --ink: #E3EDF4; --muted: #8CA4B4; --bg: #0E161C; --card: #152129;
        --border: rgba(111, 182, 228, 0.2);
      }
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: var(--font-body); color: var(--ink); background: var(--bg);
      line-height: 1.7; -webkit-font-smoothing: antialiased; }
    nav { position: sticky; top: 0; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      max-width: 820px; margin: 0 auto; padding: 0.9rem 1.5rem;
      backdrop-filter: saturate(180%) blur(16px); }
    nav .brand { display: flex; align-items: center; gap: 0.55rem; font-weight: 700;
      font-size: 1.05rem; text-decoration: none; color: var(--ink); }
    nav .brand img { width: 28px; height: 28px; border-radius: 7px; }
    nav .lang { font-size: 0.9rem; color: var(--muted); white-space: nowrap; }
    nav .lang a { margin: 0 0.15rem; text-decoration: none; color: var(--muted); }
    nav .lang a.active { color: var(--ink); font-weight: 700; }
    @media (max-width: 480px) {
      nav { flex-direction: column; gap: 0.35rem; padding: 0.7rem 1rem 0.6rem; }
    }
    main { max-width: 720px; margin: 0 auto; padding: 1.5rem 1.5rem 4rem; }
    .backlink { display: inline-block; margin-bottom: 1.6rem; color: var(--muted);
      text-decoration: none; font-size: 0.92rem; }
    .backlink:hover { color: var(--accent-deep); }
    h1 { font-family: var(--font-head); font-size: clamp(1.9rem, 5vw, 2.6rem);
      line-height: 1.18; letter-spacing: -0.02em; font-weight: 700; }
    .lead { color: var(--muted); font-size: 1.05rem; margin: 0.9rem 0 0; }
    /* App switch, ported from foldic.app's platform switch. PRO and Mobile are
       separate apps with independent version series, and stacking both lists
       buried Mobile below ten PRO rows. */
    .app-switch { display: inline-flex; gap: 0.25rem; margin: 1.6rem 0 0;
      padding: 0.25rem; border-radius: 999px;
      background: var(--card); border: 1px solid var(--border); }
    .app-switch button { display: inline-flex; align-items: center; gap: 0.4rem;
      font: inherit; font-size: 0.92rem; font-weight: 600; color: var(--muted);
      background: none; border: 0; cursor: pointer;
      padding: 0.42rem 1.05rem; border-radius: 999px; }
    .app-switch button[aria-selected="true"] { background: var(--bg); color: var(--ink);
      box-shadow: 0 1px 3px rgba(29, 94, 140, 0.14); }
    .app-switch svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; }
    /* The attribute is set by script, never in the markup: with JS off no rule
       matches and BOTH sections stay visible. foldic hard-codes it on <body>,
       which would permanently hide one app's history here. */
    body[data-app="pro"] .app-group[data-app="mobile"],
    body[data-app="mobile"] .app-group[data-app="pro"] { display: none; }
    body[data-app] .app-switch { display: inline-flex; }
    /* One section per product line. PRO and Mobile carry independent version
       series, so a single chronological list made the version column read
       backwards (1.6.0 then 1.1). Grouping is what keeps it legible. */
    /* id is app-<name> while the hash is #<name>: deliberately not the same,
       so #mobile selects the section without the browser scrolling to it —
       switching already brings it into view, and the jump hid the heading
       under the sticky nav. */
    .app-group { margin-top: 2.2rem; }
    .app-head { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap;
      padding-bottom: 0.6rem; border-bottom: 1px solid var(--border); }
    .app-head h2 { font-family: var(--font-head); font-size: 1.4rem; font-weight: 700;
      letter-spacing: -0.01em; }
    .app-head .tagline { color: var(--muted); font-size: 0.95rem; }
    .app-head .store { margin-left: auto; font-size: 0.88rem; color: var(--accent-deep);
      text-decoration: none; white-space: nowrap; }
    .app-head .store:hover { text-decoration: underline; }
    .release-list { margin-top: 1.1rem; display: flex; flex-direction: column; gap: 1rem; }
    .release { display: block; text-decoration: none; color: var(--ink);
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 1.15rem 1.4rem; transition: transform 0.15s ease; }
    a.release:hover { transform: translateY(-1px); border-color: var(--accent); }
    /* Labels cluster left, the date is pushed right. */
    .release .row { display: flex; align-items: center; justify-content: flex-start;
      gap: 0.1rem; flex-wrap: wrap; }
    /* The three labels are not equal: the version is what the row *is* (solid),
       Latest/In review is an announcement about it (pill), the platform is a
       fact about it (outlined). Sizing them alike would flatten that. */
    .release .version { font-weight: 700; font-size: 0.95rem;
      font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: var(--accent-deep); color: var(--bg);
      border-radius: 8px; padding: 0.2rem 0.6rem; display: inline-block; }
    .release .when { margin-left: auto; padding-left: 1rem; color: var(--muted);
      font-size: 0.85rem; white-space: nowrap; }
    .release .blurb { color: var(--muted); font-size: 0.93rem; margin-top: 0.45rem; }
    .release .blurb a { color: var(--accent-deep); text-decoration-color: var(--border);
      text-underline-offset: 3px; }
    .release .blurb a:hover { text-decoration-color: var(--accent-deep); }
    .latest-badge { font-size: 0.72rem; font-weight: 700; color: var(--accent-deep);
      background: var(--accent-tint); border-radius: 999px; padding: 0.1rem 0.55rem;
      margin-left: 0.4rem; vertical-align: 0.08em; text-transform: uppercase;
      letter-spacing: 0.04em; }
    /* Submitted to Apple but not approved: same shape as Latest because it is the
       same kind of label, outlined because it is a promise rather than a fact. */
    .review-badge { font-size: 0.72rem; font-weight: 700; color: var(--muted);
      border: 1px solid var(--accent); border-radius: 999px; padding: 0.1rem 0.55rem;
      margin-left: 0.4rem; vertical-align: 0.08em; text-transform: uppercase;
      letter-spacing: 0.04em; }
    .platforms { font-size: 0.72rem; font-weight: 600; color: var(--muted);
      border: 1px solid var(--border); border-radius: 999px; padding: 0.1rem 0.55rem;
      margin-left: 0.4rem; vertical-align: 0.08em; white-space: nowrap; }
    footer { max-width: 720px; margin: 0 auto; padding: 2rem 1.5rem;
      border-top: 1px solid var(--border); color: var(--muted); font-size: 0.88rem; }
    footer a { color: var(--muted); }
"""

NAV_LANGS = [("", "EN"), ("/zh", "中文"), ("/ja", "日本語"), ("/ko", "한국어")]

# Same stacks, and the same reasoning, as new-note.py: CJK locales use ONE
# stack for body and headings, because no system CJK serif pairs with the
# English display face and falling back mid-heading looks worse than not
# using a serif at all. A shared --font-head across all four locales was the
# bug this table exists to prevent.
FONTS = {
    "en": {
        "body": '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif',
        "head": '"New York", Georgia, "Times New Roman", serif',
    },
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


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(loc: str, ui: dict, releases: list, apps: list) -> str:
    prefix = ui["prefix"]
    css = CSS.replace("__FONT_BODY__", FONTS[loc]["body"]).replace(
        "__FONT_HEAD__", FONTS[loc]["head"]
    )
    lang_links = "｜".join(
        '<a href="{p}/releases/"{cls}>{label}</a>'.format(
            p=p, label=label, cls=' class="active"' if p == prefix else ""
        )
        for p, label in NAV_LANGS
    )

    groups = []
    for app in apps:
        rows = []
        for r in [x for x in releases if x["app"] == app["id"]]:
            badge = ""
            if r.get("status") == "latest":
                badge = f'<span class="latest-badge">{esc(ui["latest"])}</span>'
            elif r.get("status") == "review":
                badge = f'<span class="review-badge">{esc(ui["review"])}</span>'

            blurb = esc(r["blurb"][loc])
            if r.get("note"):
                # Note links are locale-prefixed; the slug is shared.
                blurb += ' <a href="{p}/notes/{slug}/">{label}</a>'.format(
                    p=prefix, slug=r["note"], label=esc(ui["readnote"])
                )

            rows.append(
                '        <div class="release">\n'
                '          <div class="row"><span class="version">{v}</span>{badge}'
                '<span class="platforms">{plat}</span>'
                '<span class="when">{when}</span></div>\n'
                '          <p class="blurb">{blurb}</p>\n'
                "        </div>".format(
                    v=esc(r["version"]),
                    badge=badge,
                    plat=esc(r["platforms"][loc]),
                    when=esc(r["date"][loc]),
                    blurb=blurb,
                )
            )

        groups.append(
            '    <section class="app-group" id="app-{id}" data-app="{id}">\n'
            '      <div class="app-head">\n'
            "        <h2>{name}</h2>\n"
            '        <span class="tagline">{tag}</span>\n'
            '        <a class="store" href="{store}">{store_label}</a>\n'
            "      </div>\n"
            '      <div class="release-list">\n'
            "{rows}\n"
            "      </div>\n"
            "    </section>".format(
                id=app["id"],
                name=esc(app["name"][loc]),
                tag=esc(app["tagline"][loc]),
                store=app["store"],
                store_label=esc(ui["store"]),
                rows=chr(10).join(rows),
            )
        )

    buttons = "\n".join(
        '    <button type="button" role="tab" data-app-tab="{id}" '
        'aria-controls="app-{id}" aria-selected="{sel}">{icon}{label}</button>'.format(
            id=a["id"],
            sel="true" if i == 0 else "false",
            icon=a["icon"],
            label=esc(a["toggle"][loc]),
        )
        for i, a in enumerate(apps)
    )
    switch = (
        f'  <div class="app-switch" role="tablist" aria-label="{esc(ui["switch_label"])}">\n'
        f"{buttons}\n"
        "  </div>"
    )

    footer_links = " · ".join(
        f'<a href="{prefix}{href}">{esc(label)}</a>' for href, label in ui["footer_links"]
    )
    canonical = f"https://deepsrt.com{prefix}/releases/"
    alts = "\n".join(
        '  <link rel="alternate" hreflang="{hl}" href="https://deepsrt.com{p}/releases/">'.format(
            hl=hl, p=p
        )
        for p, hl in [("", "en"), ("/zh", "zh-Hant"), ("/ja", "ja"), ("/ko", "ko")]
    )

    return f"""<!DOCTYPE html>
<html lang="{ui['lang']}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(ui['title'])}</title>
  <meta name="description" content="{esc(ui['description'])}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(ui['title'])}">
  <meta property="og:description" content="{esc(ui['description'])}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="https://deepsrt.com/og-card.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="https://deepsrt.com/og-card.png">
{alts}
  <link rel="alternate" hreflang="x-default" href="https://deepsrt.com/releases/">
  <link rel="icon" type="image/svg+xml" href="/icon.svg">
  <style>
{css}</style>
</head>
<body>
<nav>
  <a class="brand" href="{prefix}/"><img src="/icon.svg" alt=""> DeepSRT</a>
  <span class="lang">{lang_links}</span>
</nav>
<main>
  <a class="backlink" href="{prefix}/">{esc(ui['back'])}</a>
  <h1>{esc(ui['h1'])}</h1>
  <p class="lead">{esc(ui['lead'])}</p>
{switch}
{chr(10).join(groups)}
</main>
<footer>© 2026 DeepSRT · {footer_links} · <a href="mailto:tautiu.dev@gmail.com">tautiu.dev@gmail.com</a></footer>
<script>
// App switch. Defaults to the device you are reading on, so someone on an
// iPhone is not handed the Mac app's history first; #mobile / #pro in the URL
// wins, which makes either view linkable. The attribute is set here rather
// than in the markup so that with JS disabled both sections stay visible.
(function () {{
  var body = document.body;
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-app-tab]"));
  var ids = tabs.map(function (t) {{ return t.dataset.appTab; }});
  function select(app, remember) {{
    if (ids.indexOf(app) < 0) return;
    body.setAttribute("data-app", app);
    tabs.forEach(function (t) {{
      t.setAttribute("aria-selected", String(t.dataset.appTab === app));
    }});
    if (remember) {{
      try {{ localStorage.setItem("deepsrt-releases-app", app); }} catch (e) {{}}
    }}
  }}
  tabs.forEach(function (t) {{
    t.addEventListener("click", function () {{ select(t.dataset.appTab, true); }});
  }});
  var initial = ids[0];
  if (/iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent)) initial = "mobile";
  try {{
    var saved = localStorage.getItem("deepsrt-releases-app");
    if (ids.indexOf(saved) >= 0) initial = saved;
  }} catch (e) {{}}
  var hash = location.hash.replace("#", "");
  if (ids.indexOf(hash) >= 0) initial = hash;
  select(initial, false);
  window.addEventListener("hashchange", function () {{
    var h = location.hash.replace("#", "");
    if (ids.indexOf(h) >= 0) select(h, true);
  }});
}})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate and diff, write nothing")
    args = ap.parse_args()

    spec = json.loads(DATA.read_text(encoding="utf-8"))
    ui_all, releases, apps = spec["ui"], spec["releases"], spec["apps"]
    locales = list(ui_all)
    app_ids = [a["id"] for a in apps]

    # Validate before writing anything: a missing locale silently shipping an
    # empty blurb is the failure mode this guards.
    problems = []
    for app in apps:
        mine = [r for r in releases if r.get("app") == app["id"]]
        if not mine:
            problems.append(f"app {app['id']} has no releases")
        # One Latest PER APP: the product lines have independent version series,
        # so a single global Latest would be a claim about the wrong thing.
        latest = [r["version"] for r in mine if r.get("status") == "latest"]
        if len(latest) != 1:
            problems.append(f"app {app['id']}: exactly one release must be latest, found {latest}")
        for field in ("name", "tagline"):
            missing = [l for l in locales if not app.get(field, {}).get(l)]
            if missing:
                problems.append(f"app {app['id']}: {field} missing {missing}")
    for r in releases:
        if r.get("app") not in app_ids:
            problems.append(f"{r['version']}: unknown app {r.get('app')!r}")
        if r.get("status") not in STATUSES:
            problems.append(f"{r['version']}: bad status {r.get('status')!r}")
        for field in ("blurb", "platforms", "date"):
            missing = [l for l in locales if not r.get(field, {}).get(l)]
            if missing:
                problems.append(f"{r['version']}: {field} missing {missing}")
        for l in locales:
            if re.search(r"\*\*|^- ", r.get("blurb", {}).get(l, ""), re.M):
                problems.append(f"{r['version']} [{l}]: blurb looks like markdown; use HTML")
    if problems:
        print("spec problems:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    for loc, ui in ui_all.items():
        out = ROOT / ui["prefix"].lstrip("/") / "releases" / "index.html"
        html = build(loc, ui, releases, apps)
        # Same guard new-note.py carries: the English serif must never reach a
        # CJK page. A single shared --font-head is easy to reintroduce.
        if loc != "en" and "New York" in html:
            print(f"ERROR: {loc} page contains the English serif stack", file=sys.stderr)
            return 1
        if f'--font-head: {FONTS[loc]["head"]};' not in html:
            print(f"ERROR: {loc} page is missing its own font-head stack", file=sys.stderr)
            return 1
        if args.check:
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            state = "unchanged" if old == html else ("NEW" if not old else "would change")
            print(f"{state:>14}  {out.relative_to(ROOT)}")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            print(f"wrote  {out.relative_to(ROOT)}")

    print(f"\n{len(releases)} release(s), {len(locales)} locale(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
