"""compare: build the comparison page for a round from compare.json, and say whether the round is complete."""
import base64
import html
import json
import os

from direction_common import SCHEMES, Project, design_paragraph, fail, label, read, say, write

CSS = """
:root { --bg: #f5f5f7; --card: #ffffff; --text: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --accent: #0066cc; --accent-ink: #ffffff; --soft: #eef4fb; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #000000; --card: #1c1c1e; --text: #f5f5f7; --muted: #a1a1a6; --line: #38383a; --accent: #0a84ff; --accent-ink: #000000; --soft: #10253d; } }
:root[data-theme="dark"] { --bg: #000000; --card: #1c1c1e; --text: #f5f5f7; --muted: #a1a1a6; --line: #38383a; --accent: #0a84ff; --accent-ink: #000000; --soft: #10253d; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 32px; margin: 0 0 4px; } h2 { font-size: 22px; margin: 0; } h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 18px 0 6px; }
.sub { color: var(--muted); margin: 0 0 24px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 20px; margin: 0 0 20px; }
.card.base { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
.badge { display: inline-block; background: var(--accent); color: var(--accent-ink); border-radius: 980px; padding: 2px 10px; font-size: 13px; margin-left: 8px; }
.lang { color: var(--muted); margin: 6px 0 12px; } .empty { color: var(--muted); font-style: italic; }
.rec { background: var(--soft); border-color: var(--accent); } .rec dt { font-weight: 600; margin-top: 10px; } .rec dd { margin: 0; }
.grid { display: grid; grid-template-columns: 2fr 2fr 1fr 1fr; gap: 12px; align-items: start; }
figure { margin: 0; } figcaption { font-size: 13px; color: var(--muted); margin-top: 4px; }
img { max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 10px; display: block; }
.missing { border: 1px dashed var(--line); border-radius: 10px; padding: 24px 8px; color: var(--muted); text-align: center; font-size: 13px; }
ul, ol { margin: 0; padding-left: 20px; } a { color: var(--accent); } a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr 1fr; } h1 { font-size: 26px; } }
"""
EMPTY_REC = {"base": "", "borrow": "", "cost": "", "first_principles": ""}


def load_compare(p, r):
    path = p.rdir(r["n"], "compare.json")
    doc = json.loads(read(path)) if os.path.exists(path) else {}
    doc.setdefault("items", {})
    for item in r["ids"]:
        slot = doc["items"].setdefault(item, {})
        slot.setdefault("strengths", [])
        slot.setdefault("watch_outs", [])
    if r["mode"] == "options":
        doc["recommendation"] = dict(EMPTY_REC, **(doc.get("recommendation") or {}))
        doc.pop("questions", None)
    else:
        doc.setdefault("questions", [])
        doc.pop("recommendation", None)
    write(path, json.dumps(doc, indent=2) + "\n")
    return doc


def open_items(r, doc):
    """What still has to be written before the round counts as complete."""
    if r["mode"] == "options":
        return [] if str(doc["recommendation"].get("base", "")).strip() else ["recommendation.base is not set (which option do you recommend as the base?)"]
    qs = doc.get("questions") or []
    if not 2 <= len(qs) <= 4 or not all(str(q.get("question", "")).strip() for q in qs):
        return ["questions: write two to four numbered questions for the person, each with the variants that answer it differently"]
    return []


def img(p, r, name, alt):
    base = p.rdir(r["n"], "shots", name)
    for ext, mime in ((".jpg", "image/jpeg"), (".png", "image/png")):
        if os.path.exists(base + ext):
            with open(base + ext, "rb") as fh:
                return '<img alt="%s" src="data:%s;base64,%s">' % (html.escape(alt), mime, base64.b64encode(fh.read()).decode())
    return '<div class="missing">not captured yet</div>'


def lines(items, empty):
    items = [x for x in items if str(x).strip()]
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % html.escape(str(x)) for x in items) if items else '<p class="empty">%s</p>' % empty


def card(p, r, item, doc, base_id):
    slot = doc["items"][item]
    para = design_paragraph(p.item_file(r["n"], item))
    figs = ""
    for v in p.viewports():
        for s in SCHEMES:
            figs += "<figure>%s<figcaption>%s, %s</figcaption></figure>" % (img(p, r, "%s-%s-%s" % (item, v, s), "%s, %s, %s" % (label(item), v, s)), v, s)
    badge = '<span class="badge">Recommended base</span>' if base_id and base_id in (item, item.partition("-")[2], label(item), label(item).lower()) else ""
    return ('<section class="card%s"><h2>%s%s</h2><p class="lang">%s</p><div class="grid">%s</div>'
            '<h3>Strengths</h3>%s<h3>Watch-outs</h3>%s<p><a href="options/%s.html">Open the working page</a></p></section>' % (
                " base" if badge else "", html.escape(label(item)), badge,
                html.escape(para) if para else "No design-language comment at the top of this file.", figs,
                lines(slot["strengths"], "Not written yet."), lines(slot["watch_outs"], "Not written yet."), html.escape(item)))


def top(r, doc):
    if r["mode"] == "options":
        rec = doc["recommendation"]
        rows = [("Base", "base"), ("Borrow from the others", "borrow"), ("What it costs", "cost"), ("Decide this first", "first_principles")]
        body = "".join("<dt>%s</dt><dd>%s</dd>" % (t, html.escape(str(rec.get(k, ""))) or '<span class="empty">Not written yet.</span>') for t, k in rows)
        return '<section class="card rec"><h2>Recommendation</h2><dl>%s</dl></section>' % body
    qs = doc.get("questions") or []
    if not qs:
        return '<section class="card rec"><h2>Questions for you</h2><p class="empty">Not written yet.</p></section>'
    items = ""
    for q in qs:
        ans = "".join("<li>Variant %s: %s</li>" % (html.escape(str(k)), html.escape(str(v))) for k, v in (q.get("variants") or {}).items())
        items += "<li><strong>%s</strong><ul>%s</ul></li>" % (html.escape(str(q.get("question", ""))), ans)
    return '<section class="card rec"><h2>Questions for you</h2><ol>%s</ol></section>' % items


def cmd_compare(args):
    p = Project(args.dir)
    r = p.need_round(args.round)
    if not p.built(r):
        fail("Round %d has no files yet." % r["n"])
    doc = load_compare(p, r)
    base = str(doc.get("recommendation", {}).get("base", "")).strip().lower()
    cards = "".join(card(p, r, i, doc, base) for i in p.built(r))
    kind = "directions" if r["mode"] == "options" else "variants on the locked look"
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s: round %d</title><style>%s</style></head><body><main><h1>%s</h1><p class="sub">Round %d, %s. The decision is yours.</p>%s%s</main></body></html>' % (
                html.escape(p.name), r["n"], CSS, html.escape(p.name), r["n"], kind, top(r, doc), cards))
    path = p.rdir(r["n"], "index.html")
    write(path, page)
    todo = open_items(r, doc)
    r["complete"] = not todo
    p.save()
    say(args, {"round": r["n"], "page": path, "complete": r["complete"], "todo": todo},
        "wrote %s\n%s" % (path, ("The round is not complete: " + "; ".join(todo) + ". Edit %s and run compare again." % p.rdir(r["n"], "compare.json"))
                          if todo else "The round is complete. Show the person the page and ask them to pick."))
    if todo:
        raise SystemExit(1)
