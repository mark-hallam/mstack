"""Build the review report: one self-contained HTML page (pictures embedded, no external files).

It reads every round in rounds/r<N>/ (shots, verdicts, changes.md, criteria.json, people.md) and shows the
score trend toward 10, each journey this round against the last with the "if fixed" score, what changed,
what the reviewers propose, the criteria each round used, before and after screenshots for every screen,
and a filmstrip of every round. Used by eval_loop.py report.
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import availability  # noqa: E402
import readiness  # noqa: E402
from report_audit import measured  # noqa: E402
import regrade  # noqa: E402
from report_parts import (  # noqa: E402
    CSS,
    before_after,
    criteria_table,
    do_next,
    fixes_detail,
    journey_table,
    md_list,
    noise_card,
    proposals,
    trend_joined_note,
    trend_svg,
    what_changed_rounds,
)

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


def parse_views_json(raw):
    if not raw:
        return None, None
    data = json.loads(raw)
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        return data.get("views") or [], data.get("build")
    return [], None


def short_commit(commit):
    return commit[:7] if commit else None


def load_round(p, n):
    base = p.rdir(n)

    def text(name):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    crit = text("criteria.json")
    views_raw = text("views.json")
    if views_raw:
        views, build = parse_views_json(views_raw)
    else:
        views, build = p.views(), None
    return {"n": n, "verdicts": p.verdicts(n), "changes": text("changes.md"), "people": text("people.md"),
            "criteria": json.loads(crit) if crit else p.criteria(n),
            "views": views, "build": build, "shots": p.shots(n), "regrade": regrade.load_round(p, n)}


def reviewer_heading(r, verdict=None):
    name = r.get("name", r["id"])
    maker = (verdict or {}).get("maker") or r.get("maker")
    model = (verdict or {}).get("model") or r.get("model")
    if maker and model:
        name += " (%s, %s)" % (maker, model)
    elif maker:
        name += " (%s)" % maker
    return name


def reviewer_info(p, rs):
    info, order = {}, []
    palette_i = 0
    for r in p.reviewers():
        if r.get("enabled", True) is False:
            continue
        verdict = next((rr["verdicts"].get(r["id"]) for rr in reversed(rs) if r["id"] in rr.get("verdicts", {})), None)
        name = reviewer_heading(r, verdict)
        if r.get("kind") == "chat":
            saw = (verdict or {}).get("saw") or next(
                (v.get("saw") for rr in rs for who, v in rr["verdicts"].items() if who == r["id"] and v.get("saw")),
                "screenshots",
            )
            name += " (web chat, from %s; a tie breaker)" % ("the public address" if saw == "live" else "screenshots")
        info[r["id"]] = {"name": name, "colour": r.get("colour") or PALETTE[palette_i % len(PALETTE)]}
        order.append(r["id"])
        palette_i += 1
    for r in rs:
        for who in r["verdicts"]:
            if who not in info:
                info[who] = {"name": who.title(), "colour": PALETTE[len(order) % len(PALETTE)]}
                order.append(who)
    return order, info


def build(p):
    rs = [load_round(p, n) for n in p.round_numbers()]
    if not rs:
        raise SystemExit("No rounds yet. Run: start-round")
    order, info = reviewer_info(p, rs)
    for n in p.round_numbers():
        for rid in readiness.round_state(p, n)["joined"]:
            if rid in info:
                info[rid]["joined_at"] = n
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
                  "if you can, have a few first-time people try the journeys and turn what they find into the next round.</div>"
                  % (readiness.READY_SCORE, readiness.READY_SPREAD, readiness.READY_ROUNDS))
    elif latest.get("ready"):
        banner = ("<div class='banner'><b>This round passes the stopping rule.</b> Change nothing big and run one more "
                  "round so it holds for %d rounds in a row.</div>" % readiness.READY_ROUNDS)
    elif latest.get("reasons"):
        banner = "<div class='banner warn'><b>Not ready for people yet:</b> %s.</div>" % esc("; ".join(latest["reasons"]))
    short = availability.plan(p, cur["n"])
    if short["paused"]:
        banner += ("<div class='banner warn'><b>%s</b> %s.</div>" % (
            "Run with fewer reviewers, by choice: this round does not count toward ready for people." if short["choice"] == "fewer"
            else "Short one reviewer this round." if len(short["paused"]) == 1 else "Short of reviewers this round.",
            esc(short["label"])))
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
            "for like. AI scores are a strong signal, not proof.</p>%s%s"
            "%s<h2>Score trend</h2><div class='card'>%s%s</div>"
            "<h2>Each journey, this round against the last</h2><div class='card'>%s</div>%s"
            "<h2>What changed each round</h2><div class='card'>%s</div>%s"
            "%s<h2>What the reviewers propose next</h2>%s%s"
            "<h2>The criteria each round used</h2><div class='card'><p class='small sub'>The floor, plus each stage "
            "added as the product matured (highlighted).</p>%s</div>%s"
            "<h2>Before and after, screen by screen</h2>%s"
            "<p class='small sub'>Made with mStack's multi-evaluator skill.</p></div></body></html>") % (
        esc(title), CSS, esc(p.name), (". " + esc(note)) if note else "", esc(names), kpis, banner,
        do_next(p, cur, order, info), trend_svg(rs, order, info), trend_joined_note(order, info),
        journey_table(p, rs, order, info), measured(p, rs), what_changed_rounds(rs, info),
        comparisons_html(p, cur["n"], order, info), noise_card(p, rs, order, info), proposals(p, cur, order, info),
        fixes_detail(cur, order, info), criteria_table(rs), people, before_after(p, rs))
    path = os.path.join(p.dir, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    if done:
        summary = "%s round %d: ready for people (9 or better from every reviewer, held two rounds). Time for real people." % (p.name, cur["n"])
    else:
        summary = "%s round %d report ready: average %s, lowest journey %s." % (
            p.name, cur["n"], avg if avg is not None else "waiting", lowest if lowest is not None else "waiting")
    return path, summary
