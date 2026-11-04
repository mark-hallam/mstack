"""Build the review report: one self-contained HTML page (pictures embedded, no external files).

It reads every round in rounds/r<N>/ (shots, verdicts, changes.md, criteria.json, people.md) and shows the
score trend toward 10, each journey this round against the last with the "if fixed" score, what changed,
what the reviewers propose, the criteria each round used, before and after screenshots for every screen,
and a filmstrip of every round. Used by eval_loop.py report.
"""
import base64
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import readiness  # noqa: E402

PALETTE = ["#C15F3C", "#1f6feb", "#1f7a35", "#8e44ad", "#b7791f", "#0f766e"]


def esc(s):
    return html.escape("" if s is None else str(s))


def comparisons_html(p, n, order, info):
    out = []
    for who, c in p.comparisons(n).items():
        cmp_ = c.get("compare", {})
        parts = []
        for key, label in (("improved", "Improved"), ("regressed", "Got worse"), ("unchanged", "Still in the way")):
            items = cmp_.get(key) or []
            if items:
                parts.append("<p class='small sub'>%s</p><ul>%s</ul>" % (label, "".join("<li>%s</li>" % esc(i) for i in items)))
        colour = info.get(who, {}).get("colour", "#888")
        name = info.get(who, {}).get("name", who)
        out.append("<div class='card'><h3><i class='dot' style='background:%s'></i>%s compared it with last round</h3>%s%s</div>" % (
            colour, esc(name), "".join(parts) or "<p class='sub'>Nothing noted.</p>",
            "<p class='small sub'>%s</p>" % esc(cmp_["note"]) if cmp_.get("note") else ""))
    if not out:
        return ""
    return ("<p class='small sub'>A separate, labelled pass made after each verdict was saved; it never changes a score."
            "</p><div class='two'>%s</div>" % "".join(out))


def load_round(p, n):
    base = p.rdir(n)

    def text(name):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    crit = text("criteria.json")
    views = text("views.json")
    return {"n": n, "verdicts": p.verdicts(n), "changes": text("changes.md"), "people": text("people.md"),
            "criteria": json.loads(crit) if crit else p.criteria(n),
            "views": json.loads(views) if views else p.views(), "shots": p.shots(n)}


def reviewer_info(p, rs):
    info, order = {}, []
    for i, r in enumerate(p.reviewers()):
        info[r["id"]] = {"name": r.get("name", r["id"]), "colour": r.get("colour") or PALETTE[i % len(PALETTE)]}
        order.append(r["id"])
    for r in rs:
        for who in r["verdicts"]:
            if who not in info:
                info[who] = {"name": who.title(), "colour": PALETTE[len(order) % len(PALETTE)]}
                order.append(who)
    return order, info


def img(p, n, view):
    """A screenshot as an embedded image: the report sized JPEG if capture made one, else the PNG."""
    for ext, mime in (("jpg", "image/jpeg"), ("png", "image/png")):
        src = p.rdir(n, "shots", "%s.%s" % (view, ext))
        if os.path.exists(src):
            with open(src, "rb") as fh:
                return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode())
    return None


def trend_svg(rs, order, info):
    w, h, left, top, bottom = 640, 220, 44, 16, 34
    n = max(len(rs), 2)
    x = lambda i: left + (w - left - 130) * (i / (n - 1))           # noqa: E731
    y = lambda s: top + (h - top - bottom) * (1 - s / 10.0)        # noqa: E731
    parts = ['<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="target"/><text x="%d" y="%.1f" class="tl">Target 10</text>'
             % (left, w - 20, y(10), y(10), left + 4, y(10) - 6)]
    for s in (0, 5):
        parts.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/><text x="%d" y="%.1f" class="ax">%d</text>'
                     % (left, w - 20, y(s), y(s), left - 8, y(s) + 4, s))
    for i, r in enumerate(rs):
        parts.append('<text x="%.1f" y="%d" class="ax mid">Round %d</text>' % (x(i), h - 10, r["n"]))
    for who in order:
        colour = info[who]["colour"]
        pts = [(x(i), y(r["verdicts"][who]["overall"]), r["verdicts"][who]["overall"]) for i, r in enumerate(rs)
               if who in r["verdicts"] and isinstance(r["verdicts"][who].get("overall"), (int, float))]
        if not pts:
            continue
        if len(pts) > 1:
            parts.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                         % (colour, " ".join("%.1f,%.1f" % (a, b) for a, b, _ in pts)))
        for a, b, s in pts:
            parts.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="var(--card)" stroke-width="2">'
                         '<title>%s, %s</title></circle>' % (a, b, colour, esc(info[who]["name"]), s))
        a, b, s = pts[-1]
        parts.append('<text x="%.1f" y="%.1f" class="lab" fill="%s">%s %s</text>' % (
            a + 9, b + 4, colour, esc(info[who]["name"]), s))
    return '<svg viewBox="0 0 %d %d" role="img" aria-label="Overall score per round for each reviewer">%s</svg>' % (
        w, h, "".join(parts))


def journey_score(r, who, jid, key="score"):
    if not r:
        return None
    for j in r["verdicts"].get(who, {}).get("journeys", []):
        if j.get("id") == jid:
            return j.get(key)
    return None


def score_cell(cur, prev, label="", noise=0):
    lab = " data-label='%s'" % esc(label)
    if cur is None:
        return "<td class='na'%s>not scored</td>" % lab
    if prev is None:
        return "<td%s><b>%s</b></td>" % (lab, cur)
    d = cur - prev
    cls, sign = ("up", "+") if d > 0 else ("down", "") if d < 0 else ("same", "")
    within = d and abs(d) <= noise
    if within:
        cls = "same"
    return "<td%s><b>%s</b> <span class='%s'>%s%s</span><span class='was'>was %s%s</span></td>" % (
        lab, cur, cls, sign, round(d, 1) if d else "no change", prev, ", within noise" if within else "")


def journey_table(p, rs, order, info):
    cur, prev = rs[-1], rs[-2] if len(rs) > 1 else None
    names = dict((j["id"], j["name"]) for j in p.journeys())
    for r in rs:
        for v in r["verdicts"].values():
            for j in v.get("journeys", []):
                if j.get("id") != readiness.CONTROL:
                    names.setdefault(j.get("id"), j.get("name", ""))
    noise = readiness.control_noise(p) or {"per_reviewer": {}}
    rows = []
    for jid in sorted(names, key=lambda k: (str(type(k)), k)):
        cells = []
        for who in order:
            name = info[who]["name"]
            cells.append(score_cell(journey_score(cur, who, jid), journey_score(prev, who, jid), "%s now" % name,
                                    noise["per_reviewer"].get(who, 0)))
            prop = journey_score(cur, who, jid, "if_fixed")
            cells.append("<td class='prop' data-label='%s if fixed'>%s</td>" % (esc(name), prop if prop is not None else "&nbsp;"))
        fixes = [f for v in cur["verdicts"].values() for j in v.get("journeys", []) if j.get("id") == jid
                 for f in j.get("fixes", []) or []]
        high = sum(1 for f in fixes if f.get("severity") == "high")
        rows.append("<tr><th scope='row'>%s. %s</th>%s<td class='small' data-label='Fixes proposed'>%d proposed%s</td></tr>" % (
            esc(jid), esc(names[jid]), "".join(cells), len(fixes), ", %d high" % high if high else ""))
    head = "".join("<th scope='col'><i class='dot' style='background:%s'></i>%s now</th><th scope='col'>%s if fixed</th>"
                   % (info[w]["colour"], esc(info[w]["name"]), esc(info[w]["name"])) for w in order)
    return ("<table><thead><tr><th scope='col'>Journey</th>%s<th scope='col'>Fixes proposed this round</th></tr></thead>"
            "<tbody>%s</tbody></table>") % (head, "".join(rows))


def fixes_detail(cur, order, info):
    out = []
    rank = {"high": 0, "medium": 1, "low": 2}
    for who in order:
        v = cur["verdicts"].get(who)
        if not v:
            continue
        items = []
        for j in v.get("journeys", []):
            for f in sorted(j.get("fixes", []) or [], key=lambda f: rank.get(f.get("severity"), 3)):
                items.append("<li><span class='sev %s'>%s</span> <b>%s</b> (journey %s): %s <span class='sub'>Fix: %s</span></li>"
                             % (esc(f.get("severity")), esc(f.get("severity")), esc(f.get("where", "")), esc(j.get("id")),
                                esc(f.get("problem", "")), esc(f.get("fix", ""))))
        if items:
            out.append("<details class='card'><summary><i class='dot' style='background:%s'></i>Every fix %s proposed "
                       "(%d)</summary><ul class='fixes'>%s</ul></details>" % (
                           info[who]["colour"], esc(info[who]["name"]), len(items), "".join(items)))
    return "".join(out)


def before_after(p, rs):
    cur, prev = rs[-1], rs[-2] if len(rs) > 1 else None
    groups = {}
    for v in cur["views"]:
        if v["id"] in cur["shots"] or (prev and v["id"] in prev["shots"]):
            groups.setdefault(v.get("group", "Screens"), []).append(v)
    out = []
    for g, vs in groups.items():
        cards = []
        for v in vs:
            wide = v["viewport"]["w"] > 600
            after = img(p, cur["n"], v["id"]) if v["id"] in cur["shots"] else None
            before = img(p, prev["n"], v["id"]) if prev and v["id"] in prev["shots"] else None

            def fig(src, cap):
                if not src:
                    return "<figure class='empty'><div>%s</div></figure>" % esc(cap)
                return "<figure><img src='%s' alt='%s, %s'><figcaption>%s</figcaption></figure>" % (
                    src, esc(v["name"]), esc(cap), esc(cap))
            figs = ""
            if prev:
                figs += fig(before, "Before (round %d)" % prev["n"] if before else "New this round")
                figs += fig(after, "After (round %d)" % cur["n"]) if after else fig(None, "Not captured this round")
            else:
                figs += fig(after, "Round %d (the starting point)" % cur["n"])
            older = [r for r in rs if v["id"] in r["shots"]]
            strip = ""
            if len(older) > 2:
                strip = "<p class='small sub'>Every round</p><div class='strip'>%s</div>" % "".join(
                    "<figure><img src='%s' alt='%s, round %d'><figcaption>Round %d</figcaption></figure>" % (
                        img(p, r["n"], v["id"]), esc(v["name"]), r["n"], r["n"]) for r in older)
            cards.append("<div class='pair%s'><h4>%s</h4><div class='ba'>%s</div>%s</div>" % (
                "" if wide else " narrow", esc(v["name"]), figs, strip))
        out.append("<h3 class='grp'>%s</h3><div class='pairs'>%s</div>" % (esc(g), "".join(cards)))
    return "".join(out) or "<p class='sub'>No screens captured yet.</p>"


def md_list(text):
    items = [re.sub(r"^\s*[-*]\s*", "", l).strip() for l in text.splitlines() if re.match(r"^\s*[-*]\s", l)]
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % esc(i) for i in items) if items else "<p class='sub'>Not written.</p>"


def proposals(cur, order, info):
    out = []
    for who in order:
        v = cur["verdicts"].get(who)
        if not v:
            out.append("<div class='card'><h3><i class='dot' style='background:%s'></i>%s</h3><p class='sub'>No verdict "
                       "yet this round.</p></div>" % (info[who]["colour"], esc(info[who]["name"])))
            continue
        top = "".join("<li>%s</li>" % esc(t) for t in v.get("top_fixes", []))
        top = "<ol>%s</ol>" % top if top else "<p class='sub'>Nothing more to propose.</p>"
        broken = "".join("<li>%s</li>" % esc(t) for t in v.get("broken", []))
        out.append("<div class='card'><h3><i class='dot' style='background:%s'></i>%s: overall %s</h3><p class='small sub'>"
                   "Its top proposals</p>%s%s</div>" % (
                       info[who]["colour"], esc(info[who]["name"]), esc(v.get("overall")), top,
                       "<p class='small sub'>Broken or wrong</p><ul>%s</ul>" % broken if broken else ""))
    return "<div class='two'>%s</div>" % "".join(out)


def noise_card(p, rs, order, info):
    noise = readiness.control_noise(p)
    if noise is None:
        return ""
    rows = []
    for who in order:
        scores = [journey_score(r, who, readiness.CONTROL) for r in rs]
        if not any(s is not None for s in scores):
            continue
        rows.append("<tr><th scope='row'><i class='dot' style='background:%s'></i>%s</th>%s<td data-label='Moved'><b>%s</b></td></tr>" % (
            info[who]["colour"], esc(info[who]["name"]),
            "".join("<td data-label='Round %d'>%s</td>" % (r["n"], s if s is not None else "not scored") for r, s in zip(rs, scores)),
            noise["per_reviewer"].get(who, 0)))
    head = "".join("<th scope='col'>Round %d</th>" % r["n"] for r in rs)
    return ("<h2>The noise check</h2><div class='card'><p class='small sub'>Every round each reviewer also scores a frozen "
            "control (the round 1 screens, unchanged). How far that score moves is the reviewer's noise. A change in a real "
            "journey no bigger than that is marked \"within noise\" above and is not evidence of improvement. Band this "
            "review: up to <b>%s</b> point%s.</p><table><thead><tr><th scope='col'>Reviewer</th>%s<th scope='col'>Moved</th></tr>"
            "</thead><tbody>%s</tbody></table></div>" % (
                noise["band"], "" if noise["band"] == 1 else "s", head, "".join(rows) or "<tr><td>Not scored yet.</td></tr>"))


def criteria_table(rs):
    rows = []
    for r in rs:
        chips = "".join("<span class='chip%s'>%s</span>" % ("" if c.get("stage") == "Floor" else " new", esc(c["name"]))
                        for c in r["criteria"])
        rows.append("<tr><th scope='row'>Round %d</th><td>%s</td></tr>" % (r["n"], chips))
    return "<table><tbody>%s</tbody></table>" % "".join(rows)


CSS = """
:root{--page:#f2f2f7;--card:#fff;--ink:#1d1d1f;--sub:#55555b;--rule:#e2e2e7;--accent:#0a64d6;--up:#1f7a35;--down:#b3261e;
--shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.06)}
@media (prefers-color-scheme:dark){:root{--page:#000;--card:#1c1c1e;--ink:#f5f5f7;--sub:#c7c7cc;--rule:#38383c;
--accent:#7ab0f5;--up:#5bd67a;--down:#ff7a72}}
*{box-sizing:border-box}html,body{margin:0;background:var(--page);color:var(--ink)}
body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:32px;letter-spacing:-.02em;margin:0 0 6px;line-height:1.15}h2{font-size:22px;margin:36px 0 10px;letter-spacing:-.015em}
h3{font-size:16px;margin:0 0 6px}.grp{margin:22px 0 10px;color:var(--sub);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
h4{font-size:14px;margin:0 0 8px}.sub{color:var(--sub)}.small{font-size:13px}
.card{background:var(--card);border-radius:16px;box-shadow:var(--shadow);padding:18px 20px;margin-bottom:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.two .card{margin:0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}.kpis .card{margin:0}
.kpi b{display:block;font-size:30px;letter-spacing:-.02em}
.banner{background:var(--card);border-left:4px solid var(--up);border-radius:12px;padding:14px 18px;margin-top:16px}
.banner.warn{border-left-color:#b7791f}
svg{width:100%;max-width:760px;height:auto;display:block}svg .grid{stroke:var(--rule)}svg .target{stroke:var(--up);stroke-dasharray:5 5}
svg text{font:12px -apple-system,sans-serif;fill:var(--sub)}svg .tl{fill:var(--up);text-anchor:start}svg .ax{text-anchor:end}svg .mid{text-anchor:middle}
svg .lab{font-weight:700;font-size:13px;paint-order:stroke;stroke:var(--card);stroke-width:4px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 10px;border-top:1px solid var(--rule);vertical-align:top}
thead th{border-top:none;font-size:12px;color:var(--sub)}.up{color:var(--up);font-weight:600}.down{color:var(--down);font-weight:600}.same{color:var(--sub)}
.was{display:block;font-size:12px;color:var(--sub)}.prop{color:var(--sub);font-weight:600}.na{color:var(--sub)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
.chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:999px;background:var(--page);margin:2px 4px 2px 0}
.chip.new{background:var(--accent);color:#fff}
.sev{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;background:var(--page)}
.sev.high{background:var(--down);color:#fff}.fixes li{margin:8px 0}summary{cursor:pointer;font-weight:600}
.pairs{display:flex;flex-wrap:wrap;gap:14px}.pair{background:var(--card);border-radius:16px;box-shadow:var(--shadow);padding:16px;flex:1 1 100%}
.pair.narrow{flex:0 1 auto}.ba{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.narrow .ba{grid-template-columns:repeat(2,minmax(0,300px))}
figure{margin:0}figure img{width:100%;border-radius:10px;border:1px solid var(--rule);display:block}
figcaption{font-size:12px;color:var(--sub);margin-top:6px}
figure.empty div{border:1.5px dashed var(--rule);border-radius:10px;padding:40px 10px;text-align:center;color:var(--sub);font-size:13px}
.strip{display:flex;gap:8px;overflow-x:auto}.strip figure{flex:none;width:160px}
ol,ul{padding-left:20px;margin:6px 0}li{margin:3px 0}
@media (max-width:760px){.two,.kpis,.ba,.narrow .ba{grid-template-columns:1fr}.pair.narrow{flex:1 1 100%}
table,thead,tbody,tr,th,td{display:block}thead{display:none}
td[data-label]{display:flex;justify-content:flex-end;align-items:baseline;gap:6px;border-top:0;padding:4px 10px}
td[data-label]::before{content:attr(data-label);color:var(--sub);font-size:13px;font-weight:400;margin-right:auto}
td[data-label] .was{display:inline;margin-left:6px}tbody th{padding-top:14px}}
"""


def build(p):
    rs = [load_round(p, n) for n in p.round_numbers()]
    if not rs:
        raise SystemExit("No rounds yet. Run: start-round")
    order, info = reviewer_info(p, rs)
    cur = rs[-1]
    scored = [v["overall"] for v in cur["verdicts"].values() if isinstance(v.get("overall"), (int, float))]
    all_scores = [j.get("score") for v in cur["verdicts"].values() for j in v.get("journeys", [])
                  if isinstance(j.get("score"), (int, float))]
    lowest = min(all_scores) if all_scores else None
    rp = readiness.ready_for_people(p)
    done = rp["ready"]
    latest = rp["latest"] or {}
    avg = round(sum(scored) / len(scored), 1) if scored else None
    kpis = ("<div class='kpis'><div class='card kpi'><span class='small sub'>Round</span><b>%d</b></div>"
            "<div class='card kpi'><span class='small sub'>Average overall</span><b>%s</b></div>"
            "<div class='card kpi'><span class='small sub'>Lowest journey score</span><b>%s</b></div>"
            "<div class='card kpi'><span class='small sub'>Ready for people</span><b>%s</b></div></div>") % (
        cur["n"], avg if avg is not None else "waiting", lowest if lowest is not None else "waiting",
        "yes" if done else ("%d of %d rounds" % (rp["rounds_held"], rp["rounds_needed"])))
    banner = ""
    if done:
        banner = ("<div class='banner'><b>Ready for people.</b> Every journey is %d or better from every reviewer, no "
                  "high-severity fix is open, the reviewers agree within %d, and it has held for %d rounds. Now five "
                  "first-time people try the journeys. Where they disagree with the AI reviewers, the people win.</div>"
                  % (readiness.READY_SCORE, readiness.READY_SPREAD, readiness.READY_ROUNDS))
    elif latest.get("ready"):
        banner = ("<div class='banner'><b>This round passes the stopping rule.</b> Change nothing big and run one more "
                  "round so it holds for %d rounds in a row.</div>" % readiness.READY_ROUNDS)
    elif latest.get("reasons"):
        banner = "<div class='banner warn'><b>Not ready for people yet:</b> %s.</div>" % esc("; ".join(latest["reasons"]))
    if latest.get("unanimous_ten"):
        banner += ("<div class='banner warn'><b>Every reviewer gave every journey 10.</b> Treat that as a flag to double "
                   "check the brief and the journeys, not as a finish line: a perfect score from a model judge is more "
                   "often a sign the bar moved than that nothing is left.</div>")
    people = ""
    if cur["people"].strip():
        people = "<h2>Real people</h2><div class='card'>%s</div>" % md_list(cur["people"])
    names = " and ".join(info[w]["name"] for w in order) or "The reviewers"
    note = p.cfg.get("note")
    title = "%s: design review rounds" % p.name
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            "initial-scale=1'><meta name='color-scheme' content='light dark'><title>%s</title><style>%s</style></head>"
            "<body><div class='wrap'><p class='small sub'>%s, independent design review%s</p>"
            "<h1>Every round, before and after, until it is ready for people</h1>"
            "<p class='sub'>%s run every journey in a real browser each round, each in fresh context, and score it out of "
            "10 (9 or better from everyone, agreeing within a point, with no high-severity fix open, two rounds running, "
            "means ready). The same screens are captured the same way every round, so before and after compare like "
            "for like. AI scores are a strong signal, not proof: real first-time people are the final test.</p>%s%s"
            "<h2>Score trend</h2><div class='card'>%s</div>"
            "<h2>Each journey, this round against the last</h2><div class='card'>%s</div>"
            "<h2>What changed going into round %d</h2><div class='card'>%s</div>%s"
            "%s<h2>What the reviewers propose next</h2>%s%s"
            "<h2>The criteria each round used</h2><div class='card'><p class='small sub'>The floor, plus each stage "
            "added as the product matured (highlighted).</p>%s</div>%s"
            "<h2>Before and after, screen by screen</h2>%s"
            "<p class='small sub'>Made with mStack's multi-evaluator skill.</p></div></body></html>") % (
        esc(title), CSS, esc(p.name), (". " + esc(note)) if note else "", esc(names), kpis, banner,
        trend_svg(rs, order, info), journey_table(p, rs, order, info), cur["n"], md_list(cur["changes"]),
        comparisons_html(p, cur["n"], order, info), noise_card(p, rs, order, info), proposals(cur, order, info), fixes_detail(cur, order, info), criteria_table(rs), people, before_after(p, rs))
    path = os.path.join(p.dir, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    if done:
        summary = "%s round %d: ready for people (9 or better from every reviewer, held two rounds). Time for real people." % (p.name, cur["n"])
    else:
        summary = "%s round %d report ready: average %s, lowest journey %s." % (
            p.name, cur["n"], avg if avg is not None else "waiting", lowest if lowest is not None else "waiting")
    return path, summary
