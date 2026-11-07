#!/usr/bin/env python3
"""The one morning digest: what finished (with evidence), what is waiting for the person (batched questions
with defaults), and usage against the cap. A self-contained light-theme HTML page, plus a PDF and a
phone-width PNG through away-mode, and a ping through ping-me.
"""
import datetime
import html
import json
import os
import subprocess
import sys

import crew_store as st
import crew_usage as usage

CSS = """body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f5f5f7;color:#1d1d1f;
margin:0;padding:24px;line-height:1.45}main{max-width:760px;margin:0 auto}h1{font-size:28px;font-weight:700;margin:0 0 4px}
h2{font-size:17px;font-weight:600;margin:28px 0 10px}.sub{color:#6e6e73;font-size:14px}.card{background:#fff;border-radius:14px;
padding:16px 18px;margin:10px 0;box-shadow:0 1px 2px rgba(0,0,0,.06)}.row{display:flex;justify-content:space-between;gap:12px;
padding:10px 0;border-bottom:1px solid #e5e5ea}.row:last-child{border-bottom:0}.k{font-weight:600}.ev{color:#6e6e73;font-size:13px;
margin:4px 0 0}.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;background:#e8f0fe;
color:#0a58ca}.pill.ok{background:#e6f7ec;color:#1b7f3b}.pill.warn{background:#fff4e5;color:#b25e00}.pill.bad{background:#fdecec;
color:#b42318}.bar{height:8px;border-radius:4px;background:#e5e5ea;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;
background:#0a84ff}.bar i.warn{background:#ff9f0a}.bar i.bad{background:#ff453a}.tiles{display:grid;grid-template-columns:repeat(
auto-fit,minmax(150px,1fr));gap:10px}.tile{background:#fff;border-radius:14px;padding:14px 16px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.tile b{font-size:26px;display:block}.tile span{color:#6e6e73;font-size:13px}code{font-size:13px;background:#f2f2f7;padding:1px 5px;
border-radius:5px}.tile,.card{min-width:0}@media (max-width:600px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
body{padding:16px}}"""


STATUS_TOOL = os.path.join(st.SKILLS, "mstack", "scripts", "status.py")


def esc(s):
    return html.escape(str(s))


def since(stamp_text, hours=24):
    try:
        return (st.now() - datetime.datetime.fromisoformat(stamp_text[:19])).total_seconds() <= hours * 3600
    except ValueError:
        return False


def gather(cfg, q, hours=24):
    jobs = q["jobs"]
    finished = [j for j in jobs if j["state"] == "done" and since(j.get("finished", ""), hours)]
    waiting = [x for x in q["questions"] if not x.get("answer")]
    stuck = [j for j in jobs if j["state"] in ("blocked", "failed") and since(j.get("finished", ""), hours)]
    todo = [j for j in jobs if j["state"] == "todo"]
    tokens = sum(int(j.get("usage", {}).get("total_tokens", 0)) for j in finished)
    budgets = {}
    for r in st.RUNNERS:
        budgets[r] = usage.runner_budget(cfg, r, q, allow_probe=False)
    all_done = [j for j in jobs if j["state"] == "done"]
    all_tokens = sum(int(j.get("usage", {}).get("total_tokens", 0)) for j in all_done)
    return {"date": st.now().date().isoformat(), "finished": finished, "waiting": waiting, "stuck": stuck, "todo": todo,
            "tokens": tokens, "budgets": budgets,
            "north_star": {"outcomes_without_the_person": len(all_done),
                           "tokens_per_outcome": int(all_tokens / len(all_done)) if all_done else 0}}


def usage_html(budgets):
    out = []
    for name, b in budgets.items():
        r = b.get("reading")
        if not r:
            out.append("<div class='row'><div><span class='k'>%s</span><p class='ev'>%s</p></div><span class='pill warn'>not readable</span></div>"
                       % (esc(name), esc(b["why"])))
            continue
        for w in r["windows"]:
            cls = "bad" if w["percent"] >= b["cap"] else ("warn" if w["percent"] >= b["cap"] - 15 else "")
            out.append("<div class='row'><div style='flex:1'><span class='k'>%s, %s window</span> <span class='sub'>%.0f%% used, cap %.0f%%, resets %s</span>"
                       "<div class='bar'><i class='%s' style='width:%d%%'></i></div><p class='ev'>read from %s at %s</p></div></div>" % (
                           esc(name), esc(w["window"].replace("_", " ")), w["percent"], b["cap"], esc(w.get("resets") or "?"), cls,
                           min(100, int(w["percent"])), esc(r.get("how", "")), esc(r.get("at", "")[:16])))
    return "".join(out)


def build_html(d):
    rows = []
    for j in d["finished"]:
        ev = "".join("<p class='ev'>%s</p>" % esc(e) for e in j.get("evidence", [])[:6])
        tok = j.get("usage", {}).get("total_tokens")
        tok_lbl = ("%s tokens" % format(tok, ",")) if tok else "done"
        if tok and j.get("tier") == "small" and int(tok) > 200000:
            tok_lbl += ", heavy for its tier"
        rows.append("<div class='row'><div><span class='k'>%s</span> <span class='sub'>%s, %s</span>%s</div><span class='pill ok'>%s</span></div>" % (
            esc(j["title"]), esc(j["project"]), esc(j.get("runner_used", "")), ev, esc(tok_lbl)))
    finished = "".join(rows) or "<p class='sub'>Nothing finished in the last day.</p>"
    waits = []
    for i, x in enumerate(d["waiting"], 1):
        waits.append("<div class='row'><div><span class='k'>%d. %s</span><p class='ev'>Default: %s</p><p class='ev'>Answer with "
                     "<code>crew.py answer %s \"yes\"</code> (or your own words)</p></div></div>" % (
                         i, esc(x["question"]), esc(x.get("default") or "none"), esc(x.get("job") or x["key"])))
    for j in d["stuck"]:
        waits.append("<div class='row'><div><span class='k'>%s</span> <span class='sub'>%s</span><p class='ev'>%s</p>"
                     "<p class='ev'><code>crew.py retry %s</code> to try once more, or <code>crew.py drop %s</code></p></div>"
                     "<span class='pill bad'>%s</span></div>" % (esc(j["title"]), esc(j["project"]), esc(j.get("note", "")),
                                                               esc(j["id"]), esc(j["id"]), esc(j["state"])))
    waiting = "".join(waits) or "<p class='sub'>Nothing is waiting for you.</p>"
    ns = d["north_star"]
    page = ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='color-scheme' content='light only'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Crew digest %s</title><style>%s</style></head><body><main>"
            "<h1>Your crew, %s</h1><p class='sub'>What finished while you were away, what needs you, and the usage it took.</p>"
            "<p class='sub'>Everything across your projects: <code>%s</code></p>"
            "<div class='tiles'><div class='tile'><b>%d</b><span>finished in the last day</span></div>"
            "<div class='tile'><b>%d</b><span>waiting for you</span></div>"
            "<div class='tile'><b>%s</b><span>tokens used by finished jobs (cached reads included)</span></div>"
            "<div class='tile'><b>%d</b><span>outcomes finished without you, all time</span></div>"
            "<div class='tile'><b>%s</b><span>tokens per finished outcome</span></div></div>"
            "<h2>Finished, with evidence</h2><div class='card'>%s</div>"
            "<h2>Waiting for you</h2><div class='card'>%s</div>"
            "<h2>Usage against the cap</h2><div class='card'>%s</div>"
            "<h2>Still queued</h2><div class='card'><p class='sub'>%d jobs queued. <code>crew.py list</code> shows them.</p></div>"
            "</main></body></html>") % (
        esc(d["date"]), CSS, esc(d["date"]), esc("python3 %s status --render" % STATUS_TOOL), len(d["finished"]), len(d["waiting"]) + len(d["stuck"]), format(d["tokens"], ","),
        ns["outcomes_without_the_person"], format(ns["tokens_per_outcome"], ","), finished, waiting, usage_html(d["budgets"]), len(d["todo"]))
    return page


def render_phone(path):
    """A PDF and a phone-width PNG through away-mode's renderer, when it is there. Says what it could not do."""
    tool = os.path.join(st.SKILLS, "away-mode", "scripts", "away_render.py")
    if not os.path.exists(tool) or os.environ.get("MSTACK_CREW_NO_RENDER") == "1":
        return {"notes": ["away-mode's renderer not used"]}
    try:
        r = subprocess.run([sys.executable, tool, path, "--out", os.path.dirname(path)], capture_output=True, text=True, timeout=600)
        return json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"notes": ["render failed: %s" % e]}


def ping(message):
    tool = os.path.join(st.SKILLS, "mstack", "scripts", "mstack.py")
    if not os.path.exists(tool) or os.environ.get("MSTACK_CREW_NO_PING") == "1":
        return "not sent"
    try:
        r = subprocess.run([sys.executable, tool, "ping", message, "--title", "Crew"], capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return "ping failed: %s" % e


def make_digest(cfg, q, send=True):
    d = gather(cfg, q)
    folder = st.home("digests")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s.html" % d["date"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_html(d))
    rendered = render_phone(path)
    waiting = len(d["waiting"]) + len(d["stuck"])
    line = "Crew digest: %d finished, %d waiting for you, %s tokens. %s" % (
        len(d["finished"]), waiting, format(d["tokens"], ","), "Questions have defaults: say go or answer." if waiting else "Nothing needs you.")
    sent = ping(line) if send else "not sent"
    files = [f.get("path", "") for f in rendered.get("files", [])]
    pdf = next((f for f in files if f.endswith(".pdf")), "")
    png = next((f for f in files if f.endswith(".png")), "")
    return {"html": path, "pdf": pdf, "png": png, "files": files, "notes": rendered.get("notes", []),
            "line": line, "ping": sent, "finished": len(d["finished"]), "waiting": waiting, "north_star": d["north_star"]}
