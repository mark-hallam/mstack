#!/usr/bin/env python3
"""Evaluator scoreboard: a running record of every multi-evaluator round, and how far each AI reviewer can be trusted.

Every round, each reviewer scores the product's journeys (0 to 10). Where a round also has critique checks (a
separate checker model re-tests each reviewer's findings in the live product, see critique.py), the reviewer gets a
critique-quality score, an accuracy figure and the share of its serious findings that held up. Over many rounds and
projects this becomes the person's own evaluation of evaluators.

    python3 evalboard.py record --dir <review folder> --round <N> [--project "<name>"] [--checker "<model>"]
    python3 evalboard.py backfill --dir <review folder> [--project "<name>"]
    python3 evalboard.py board [--out <file>] [--public] [--json]

eval_loop.py runs `record` by itself after every saved verdict, critique check and report. The ledger
(ledger.jsonl, one line per reviewer per round) and the scoreboard live in the person's private mStack home,
$MSTACK_HOME/evals (default ~/.mstack/evals), never in a repository: the tool refuses a home inside a git
repository. `board --public` writes a copy with project names replaced by "Project A", "Project B" and so on and
the checker's notes left out, for publishing; scan it before it goes anywhere.
Python 3.9 or later, standard library only.
"""
import argparse
import datetime
import glob
import html
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import critique  # noqa: E402

CONFIG_NAME = "mstack-eval.json"


def home():
    """The private folder that holds the ledger: $MSTACK_HOME/evals, else ~/.mstack/evals. Never inside a git repository."""
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    path = os.path.abspath(os.path.join(os.path.expanduser(base), "evals"))
    d = path
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            raise SystemExit("The evaluator ledger would be inside the git repository at %s. It is private: set "
                             "MSTACK_HOME to a folder outside every repository." % d)
        up = os.path.dirname(d)
        if up == d:
            return path
        d = up


def ledger_path():
    return os.path.join(home(), "ledger.jsonl")


def load():
    path = ledger_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def save(rows):
    os.makedirs(home(), exist_ok=True)
    rows.sort(key=lambda r: (r["project"], r["round"], r["reviewer"]))
    tmp = ledger_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, ledger_path())


def reviewer_info(cfg, rid, v):
    r = next((r for r in cfg.get("reviewers", []) if r.get("id") == rid), {})
    return {"name": r.get("name", rid), "maker": v.get("maker") or r.get("maker") or "?", "model": v.get("model") or r.get("model")}


def round_records(project, d, n, checker_name):
    with open(os.path.join(d, CONFIG_NAME), encoding="utf-8") as fh:
        cfg = json.load(fh)
    rd = os.path.join(d, "rounds", "r%d" % n)
    out = []
    for path in sorted(glob.glob(os.path.join(rd, "verdicts", "*.json"))):
        rid = os.path.basename(path)[:-5]
        if rid.endswith((".compare", "-compare", "-regrade")):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                v = json.load(fh)
        except ValueError:
            continue
        js = [j for j in v.get("journeys", []) if isinstance(j, dict) and isinstance(j.get("id"), int)
              and isinstance(j.get("score"), (int, float))]
        if not js:
            continue
        sev = {}
        for j in js:
            for f in j.get("fixes", []) or []:
                if isinstance(f, dict):
                    sev[f.get("severity", "?")] = sev.get(f.get("severity", "?"), 0) + 1
        rec = {"project": project, "round": int(n), "date": datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat(),
               "reviewer": rid, **reviewer_info(cfg, rid, v),
               "journey_scores": {str(j["id"]): j["score"] for j in js},
               "app_score": round(statistics.mean(j["score"] for j in js), 2),
               "findings": sum(sev.values()), "findings_by_severity": sev}
        mp = os.path.join(rd, "meta", rid + ".json")
        if os.path.exists(mp):
            try:
                with open(mp, encoding="utf-8") as fh:
                    m = json.load(fh)
            except ValueError:
                m = None
            if isinstance(m, dict):
                s = critique.summary(m)
                cal = [c for c in m.get("calibration", []) or [] if isinstance(c, dict) and isinstance(c.get("journey"), int)
                       and isinstance(c.get("their_score"), (int, float)) and isinstance(c.get("your_score"), (int, float))]
                # score error over all journeys: journeys the checker left alone count as no difference
                s["calibration_error"] = round(sum(abs(c["their_score"] - c["your_score"]) for c in cal) / max(1, len(js)), 2)
                s["checker"] = m.get("checker") or checker_name
                rec["check"] = s
        out.append(rec)
    if out:   # how strict each reviewer was compared with the others that round
        mean = statistics.mean(r["app_score"] for r in out)
        for r in out:
            r["strictness"] = round(r["app_score"] - mean, 2)
    return out


def record(project, d, n, checker_name):
    """Replace this project's round n in the ledger with what the review folder holds now. Returns the new rows."""
    rows = [r for r in load() if not (r["project"] == project and r["round"] == n)]
    new = round_records(project, d, n, checker_name)
    save(rows + new)
    return new


def record_project(p, n):
    """What eval_loop runs after a verdict, a critique check or a report. Off when the config says "scoreboard": false."""
    if p.cfg.get("scoreboard") is False:
        return "off (scoreboard is false in %s)" % CONFIG_NAME
    new = record(p.name, p.dir, n, critique.checker(p)["name"])
    board_path = write_board(load())
    return "recorded %d reviewer(s) for round %d: %s" % (len(new), n, board_path)


def project_name(a):
    if a.project:
        return a.project
    with open(os.path.join(a.dir, CONFIG_NAME), encoding="utf-8") as fh:
        return json.load(fh).get("name", "Untitled")


def cmd_record(a):
    new = record(project_name(a), os.path.abspath(a.dir), a.round, a.checker)
    print("recorded %d reviewer(s) for %s round %d: %s" % (len(new), project_name(a), a.round, ", ".join(
        "%s %s%s" % (r["name"], r["app_score"], " (critique %s/10)" % r["check"]["critique_quality"] if r.get("check") else "")
        for r in new)))


def cmd_backfill(a):
    d = os.path.abspath(a.dir)
    project = project_name(a)
    rounds = sorted(int(os.path.basename(x)[1:]) for x in glob.glob(os.path.join(d, "rounds", "r*"))
                    if os.path.basename(x)[1:].isdigit())
    rows = [r for r in load() if r["project"] != project]
    for n in rounds:
        rows += round_records(project, d, n, a.checker)
    save(rows)
    print("backfilled %s: %s, %d records" % (project, "rounds %d to %d" % (rounds[0], rounds[-1]) if rounds else "no rounds",
                                           sum(r["project"] == project for r in rows)))


# ---------------------------------------------------------------- scoreboard
def wavg(items, key, weight):
    w = sum(weight(i) for i in items if key(i) is not None)
    return sum(key(i) * weight(i) for i in items if key(i) is not None) / w if w else None


def board(rows, public):
    e = html.escape
    if public:
        names = {p: f"Project {chr(65 + i)}" for i, p in enumerate(sorted({r["project"] for r in rows}))}
        rows = [{**r, "project": names[r["project"]], "check": {**r["check"], "summary": ""} if r.get("check") else None} for r in rows]
    by = {}
    for r in rows:
        by.setdefault(r["name"], []).append(r)
    stats = []
    for name, rs in by.items():
        ck = [r["check"] for r in rs if r.get("check")]
        stats.append({
            "name": name, "maker": rs[0]["maker"], "rounds": len(rs), "checked_rounds": len(ck), "projects": len({r["project"] for r in rs}),
            "quality": wavg(ck, lambda c: c.get("critique_quality"), lambda c: max(1, c["checked"])),
            "accuracy": wavg(ck, lambda c: c.get("accuracy"), lambda c: max(1, c["checked"])),
            "serious_held": (sum(c["serious_held"] for c in ck) / sum(c["serious"] for c in ck)) if sum(c["serious"] for c in ck) else None,
            "severity_ok": wavg(ck, lambda c: c.get("severity_ok"), lambda c: max(1, c["checked"])),
            "fix_quality": wavg(ck, lambda c: c.get("fix_quality"), lambda c: max(1, c["checked"])),
            "cal_err": wavg(ck, lambda c: c.get("calibration_error"), lambda c: 1),
            "findings_checked": sum(c["checked"] for c in ck), "wrong": sum(c["wrong"] + c["not_reproduced"] for c in ck),
            "strictness": statistics.mean(r.get("strictness", 0) for r in rs), "app": statistics.mean(r["app_score"] for r in rs),
            "last": max(r["date"] for r in rs)})
    ranked = sorted([s for s in stats if s["quality"] is not None], key=lambda s: (-s["quality"], -(s["accuracy"] or 0))) + sorted([s for s in stats if s["quality"] is None], key=lambda s: s["name"])
    f1 = lambda x, d=1: "·" if x is None else f"{x:.{d}f}"
    pct = lambda x: "·" if x is None else f"{round(100 * x)}%"
    rows_rank = ""
    for i, s in enumerate(ranked):
        medal = ["gold", "silver", "bronze"][i] if i < 3 and s["quality"] is not None else ""
        bar = f"<span class=bar><i style='width:{(s['quality'] or 0) * 10}%'></i></span>" if s["quality"] is not None else ""
        rows_rank += (f"<tr><td class=rank><span class='pos {medal}'>{i + 1 if s['quality'] is not None else ''}</span></td><td style='white-space:nowrap'><b>{e(s['name'])}</b><div class=muted>{e(s['maker'])}</div></td>"
                      f"<td class=n><b>{f1(s['quality'])}</b>{bar}</td><td class=n>{pct(s['accuracy'])}</td><td class=n>{pct(s['serious_held'])}</td><td class=n>{pct(s['severity_ok'])}</td>"
                      f"<td class=n>{pct(s['fix_quality'])}</td><td class=n>{f1(s['cal_err'], 2)}</td><td class=n>{('+' if s['strictness'] > 0 else '')}{s['strictness']:.2f}</td>"
                      f"<td class=n>{s['checked_rounds']} / {s['rounds']}</td><td class=n>{s['findings_checked']}</td></tr>")

    # history chart: critique quality per reviewer over checked rounds (x = project round order)
    checked = sorted({(r["project"], r["round"]) for r in rows if r.get("check")})
    palette = ["#0071e3", "#bf5af2", "#34c759", "#ff9f0a", "#ff375f", "#64d2ff", "#8e8e93"]
    W, H, P = 760, 260, 40
    svg_lines, legend = "", ""
    if checked:
        xs = {k: P + (i * (W - 2 * P) / max(1, len(checked) - 1) if len(checked) > 1 else (W - 2 * P) / 2) for i, k in enumerate(checked)}
        y = lambda v: H - P - v * (H - 2 * P) / 10
        grid = "".join(f"<line x1={P} x2={W - P} y1={y(v)} y2={y(v)} class=grid /><text x={P - 8} y={y(v) + 4} class=ax text-anchor=end>{v}</text>" for v in (0, 2, 4, 6, 8, 10))
        ticks = "".join(f"<text x={x} y={H - P + 18} class=ax text-anchor=middle>{e(p[:10])} r{n}</text>" for (p, n), x in xs.items())
        for i, s in enumerate(ranked):
            pts = sorted(((r["project"], r["round"]), r["check"]["critique_quality"]) for r in rows if r["name"] == s["name"] and r.get("check") and r["check"].get("critique_quality") is not None)
            if not pts:
                continue
            col = palette[i % len(palette)]
            path = " ".join(f"{'M' if j == 0 else 'L'}{xs[k]:.1f},{y(v):.1f}" for j, (k, v) in enumerate(pts))
            svg_lines += f"<path d='{path}' fill=none stroke='{col}' stroke-width=2.5 />" + "".join(f"<circle cx={xs[k]:.1f} cy={y(v):.1f} r=4.5 fill='{col}'><title>{e(s['name'])}: {v}/10</title></circle>" for k, v in pts)
            legend += f"<span class=lg><i style='background:{col}'></i>{e(s['name'])}</span>"
        chart = f"<svg viewBox='0 0 {W} {H}' role=img aria-label='Critique quality over time'>{grid}{ticks}{svg_lines}</svg><div class=legend>{legend}</div>"
    else:
        chart = "<p class=muted>No critique checks recorded yet.</p>"

    # app scores given, per round
    allr = sorted({(r["project"], r["round"]) for r in rows})
    names = [s["name"] for s in ranked]
    hist = "".join(f"<tr><td>{e(p)}</td><td class=n>{n}</td>" + "".join(
        (lambda m: f"<td class=n>{m['app_score']:.1f}" + (f"<div class=q>{m['check']['critique_quality']}/10</div>" if m.get("check") else "") + "</td>" if m else "<td class='n muted'>·</td>")(
            next((r for r in rows if r["project"] == p and r["round"] == n and r["name"] == nm), None)) for nm in names) + "</tr>" for p, n in reversed(allr))
    heads = "".join(f"<th class=n>{e(nm.replace('Claude ', ''))}</th>" for nm in names)
    total_checked = sum(s["findings_checked"] for s in stats)
    updated = datetime.date.today().isoformat()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluator Scoreboard</title><style>
:root {{ --bg:#f5f5f7; --card:#fff; --text:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --accent:#0071e3; --track:#e8e8ed; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#000; --card:#1c1c1e; --text:#f5f5f7; --muted:#a1a1a6; --line:#38383a; --accent:#2997ff; --track:#2c2c2e; }} }}
:root[data-theme="dark"] {{ --bg:#000; --card:#1c1c1e; --text:#f5f5f7; --muted:#a1a1a6; --line:#38383a; --accent:#2997ff; --track:#2c2c2e; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:40px 16px 72px; }} h1 {{ font-size:40px; letter-spacing:-.025em; margin:0; }} h2 {{ font-size:22px; margin:40px 0 12px; }}
.sub, .muted {{ color:var(--muted); }} .muted {{ font-size:13px; }} .card {{ background:var(--card); border-radius:16px; padding:20px 22px; margin:14px 0; box-shadow:0 1px 2px rgba(0,0,0,.05); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:12px; margin:22px 0 0; }} .stat {{ background:var(--card); border-radius:14px; padding:14px 18px; }}
.stat b {{ display:block; font-size:28px; letter-spacing:-.02em; }} .stat span {{ color:var(--muted); font-size:14px; }}
.wrap {{ overflow-x:auto; background:var(--card); border-radius:16px; }} table {{ width:100%; border-collapse:collapse; font-size:15px; }}
td, th {{ padding:11px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }} tr:last-child td {{ border-bottom:0; }}
th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }} .n {{ text-align:right; white-space:nowrap; }}
.rank {{ width:44px; }} .pos {{ display:inline-grid; place-items:center; width:28px; height:28px; border-radius:14px; font-weight:700; font-size:14px; background:var(--track); }}
.pos.gold {{ background:#ffd60a; color:#3a2a00; }} .pos.silver {{ background:#d1d1d6; color:#1d1d1f; }} .pos.bronze {{ background:#d6a477; color:#2f1b08; }}
.bar {{ display:block; height:6px; width:90px; margin:6px 0 0 auto; background:var(--track); border-radius:3px; overflow:hidden; }} .bar i {{ display:block; height:100%; background:var(--accent); }}
.q {{ font-size:12px; color:var(--accent); }} svg {{ width:100%; height:auto; display:block; }} .grid {{ stroke:var(--line); }} .ax {{ fill:var(--muted); font-size:11px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; font-size:14px; }} .lg i {{ display:inline-block; width:10px; height:10px; border-radius:5px; margin-right:6px; vertical-align:middle; }}
dl {{ margin:0; }} dt {{ font-weight:600; margin-top:10px; }} dd {{ margin:2px 0 0; color:var(--muted); }}
</style></head><body><main>
<h1>Evaluator Scoreboard</h1><p class=sub>How far each AI design reviewer can be trusted, measured round after round · updated {updated}</p>
<div class=stats><div class=stat><b>{len(allr)}</b><span>review rounds recorded</span></div><div class=stat><b>{len(stats)}</b><span>evaluators</span></div>
<div class=stat><b>{len(checked)}</b><span>rounds with critique checks</span></div><div class=stat><b>{total_checked}</b><span>findings re-tested</span></div></div>
<h2>Ranking</h2><div class=wrap><table><tr><th></th><th>Evaluator</th><th class=n>Critique quality</th><th class=n>Accuracy</th><th class=n>Serious findings held</th><th class=n>Severity right</th><th class=n>Fix quality</th><th class=n>Score error</th><th class=n>Strictness</th><th class=n>Checked / rounds</th><th class=n>Findings checked</th></tr>{rows_rank}</table></div>
<p class=muted>Ranked by critique quality, weighted by how many findings were checked. Evaluators without a critique check are listed last.</p>
<h2>Critique quality over time</h2><div class=card>{chart}</div>
<h2>Every round</h2><div class=wrap><table><tr><th>Project</th><th class=n>Round</th>{heads}</tr>{hist}</table></div>
<p class=muted>Each cell is the evaluator's average journey score for the product (0 to 10); where its critique was checked, the critique-quality score is shown underneath.</p>
<h2>Method</h2><div class=card><dl>
<dt>Reviewing</dt><dd>Each evaluator gets the same blind brief, drives the real product in a real browser in fresh context, and scores every user journey 0 to 10 with fixes and severities. Evaluators never see each other's work or earlier rounds.</dd>
<dt>Critique check</dt><dd>A separate checker model, in fresh context, re-tests every blocker, high and medium finding in the live product and marks it confirmed, partly true, not reproduced or wrong; judges whether the severity fits and how good the fix is; names important problems the evaluator missed; and says which journey scores it would change.</dd>
<dt>Critique quality</dt><dd>The checker's overall 0 to 10 rating, weighing accuracy, severity judgement, fix quality, score calibration and coverage.</dd>
<dt>Accuracy</dt><dd>Share of checked findings that were confirmed or partly true. Serious findings held: the same for blocker and high findings only.</dd>
<dt>Score error</dt><dd>Average gap, per journey, between the evaluator's score and the checker's, counting journeys the checker left alone as zero. Lower is better.</dd>
<dt>Strictness</dt><dd>How much lower (minus) or higher (plus) the evaluator scored the product than the other evaluators in the same round. A matter of style, not quality.</dd>
<dt>Limits</dt><dd>The checker is itself an AI model and can be wrong; it never checks its own review in the same context. AI scores are a strong signal, not proof: when real people disagree with the evaluators, the real people win.</dd>
</dl></div>
</main></body></html>"""


def write_board(rows, public=False, out=None):
    out = os.path.abspath(os.path.expanduser(out or os.path.join(home(), "scoreboard-public.html" if public else "scoreboard.html")))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(board(rows, public))
    return out


def cmd_board(a):
    rows = load()
    path = write_board(rows, a.public, a.out)
    if a.json:
        print(json.dumps({"scoreboard": path, "public": a.public, "records": len(rows),
                          "projects": len({r["project"] for r in rows})}, indent=2))
    else:
        print(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "backfill"):
        s = sp.add_parser(name)
        s.add_argument("--dir", default=".", help="the review folder that holds %s" % CONFIG_NAME)
        s.add_argument("--project", help="the project's name on the scoreboard (default: the config's name)")
        s.add_argument("--checker", default=critique.DEFAULT_CHECKER["name"], help="who checked the critiques")
        if name == "record":
            s.add_argument("--round", type=int, required=True)
    b = sp.add_parser("board")
    b.add_argument("--out", help="where to write the page (default: the private mStack home)")
    b.add_argument("--public", action="store_true", help="project names replaced and the checker's notes left out")
    b.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    {"record": cmd_record, "backfill": cmd_backfill, "board": cmd_board}[a.cmd](a)


if __name__ == "__main__":
    main()
