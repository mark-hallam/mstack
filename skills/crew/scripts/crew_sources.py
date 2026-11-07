#!/usr/bin/env python3
"""Where crew's work comes from. Each project declares its sources in the config; a scan turns them into jobs.

Source kinds:
  plan       a Markdown plan or backlog: every unticked "- [ ]" item (or a "TODO:" line) becomes a job
  evaluator  a multi-evaluator review folder: the latest round's "Do these next" fixes, batched per journey
  tests      the project's test command: when it fails, one job "make the tests pass" with the failing tail
  daily      a job the person wants every day (idea mining, an inbox check, a follow-up draft), once per day

Nothing here calls a model. Running the tests is local, and only when the project asks for it.
"""
import glob
import json
import os
import re
import subprocess

import crew_store as st

SMALL_WORDS = ("typo", "rename", "lint", "format", "bump", "comment", "docstring", "wording", "copy", "spelling", "label")
TOP_WORDS = ("design", "architecture", "redesign", "rethink", "strategy", "model the", "first principles", "security review")
CHROME_MARKERS = ("chrome", "drive.mjs", "eval_loop", "away.py render", "selftest", "run_all")


def job_needs_chrome(job, project):
    if str(job.get("source", "")).startswith("evaluator"):
        return True
    parts = []
    if project.get("test"):
        parts.append(project["test"])
    for d in job.get("done", []):
        parts.append(d)
    parts.append(job.get("source", ""))
    blob = " ".join(parts).lower()
    return any(m in blob for m in CHROME_MARKERS)


def apply_needs(job, project):
    needs = set(job.get("needs") or [])
    if job_needs_chrome(job, project):
        needs.add("chrome")
    if needs:
        job["needs"] = sorted(needs)


def guess_tier(text):
    low = text.lower()
    if any(w in low for w in TOP_WORDS):
        return "top"
    if any(w in low for w in SMALL_WORDS):
        return "small"
    return "fast"


def mentioned_files(text, root):
    """Paths named in the text that exist in the project: the job's small context."""
    out = []
    for m in re.findall(r"[`']?([\w./-]+\.[A-Za-z0-9]{1,6})[`']?", text):
        if os.path.exists(os.path.join(root, m)) and m not in out:
            out.append(m)
    return out


def done_checks(p, extra=None):
    checks = []
    if p.get("test"):
        checks.append("The project's tests pass::%s" % p["test"])
    checks += list(extra or [])
    return checks


# ---------------------------------------------------------------- plan files

def jobs_from_plan(p, src):
    path = os.path.join(p["path"], src["file"])
    if not os.path.exists(path):
        return [], "plan file not found: %s" % path
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    jobs, limit = [], int(src.get("max", 20))
    for line in lines:
        m = re.match(r"\s*(?:[-*]\s*\[ \]|TODO:)\s*(.+)", line)
        if not m:
            continue
        item = m.group(1).strip()
        if len(item) < 8:
            continue
        tier = src.get("tier") or guess_tier(item)
        j = st.new_job(p["id"], item, tier=tier, files=mentioned_files(item, p["path"]),
                       done=done_checks(p, ["The plan item is done and ticked in %s" % src["file"]]),
                       source="plan:%s" % src["file"], key="plan:" + item, stream=p["stream"],
                       runner=src.get("runner", "auto"),
                       context="From the plan %s. Tick the item in the plan when it is done." % src["file"])
        apply_needs(j, p)
        jobs.append(j)
        if len(jobs) >= limit:
            break
    return jobs, ""


# ---------------------------------------------------------------- evaluator rounds

def latest_round(folder):
    rounds = sorted(glob.glob(os.path.join(folder, "rounds", "r*")), key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)) or 0))
    rounds = [r for r in rounds if glob.glob(os.path.join(r, "verdicts", "*.json"))]
    return rounds[-1] if rounds else ""


def load_verdicts(rdir):
    out = {}
    for path in glob.glob(os.path.join(rdir, "verdicts", "*.json")):
        name = os.path.basename(path)[:-5]
        if name.endswith("-compare"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                out[name] = json.load(fh)
        except (OSError, ValueError):
            pass
    return out


def ranked_fixes(verdicts):
    """The same rule as the multi-evaluator report: fixes on a journey every reviewer flagged first, then
    high severity, then the biggest "if fixed" gap."""
    flagged = {}
    for who, v in verdicts.items():
        for j in v.get("journeys", []):
            if j.get("fixes"):
                flagged.setdefault(j.get("id"), set()).add(who)
    sev = {"high": 0, "medium": 1, "low": 2}
    items = []
    for who, v in verdicts.items():
        for j in v.get("journeys", []):
            gap = float(j.get("if_fixed", 0) or 0) - float(j.get("score", 0) or 0)
            for f in j.get("fixes", []):
                items.append({"journey": j.get("id"), "journey_name": j.get("name", ""), "reviewer": who,
                              "severity": f.get("severity", "medium"), "where": f.get("where", ""),
                              "problem": f.get("problem", ""), "fix": f.get("fix", ""),
                              "agreed": len(flagged.get(j.get("id"), ())) >= 2 and len(verdicts) >= 2, "gap": gap})
    items.sort(key=lambda it: (not it["agreed"], sev.get(it["severity"], 1), -it["gap"]))
    return items


def jobs_from_evaluator(p, src):
    folder = os.path.expanduser(src["dir"]) if os.path.isabs(os.path.expanduser(src["dir"])) else os.path.join(p["path"], src["dir"])
    rdir = latest_round(folder)
    if not rdir:
        return [], "no round with verdicts in %s" % folder
    items = ranked_fixes(load_verdicts(rdir))
    if not items:
        return [], ""
    by_journey = {}
    for it in items:
        by_journey.setdefault(it["journey"], []).append(it)
    jobs, rname = [], os.path.basename(rdir)
    for jid, fixes in by_journey.items():
        worst = fixes[0]
        lines = ["%s (%s, %s): %s%s" % (f["reviewer"], f["severity"], f["where"] or "the product", f["fix"],
                                       (" Problem: " + f["problem"]) if f["problem"] else "") for f in fixes]
        title = "Fix journey %s (%s): %d review finding%s from %s" % (jid, worst["journey_name"] or "unnamed", len(fixes),
                                                                      "" if len(fixes) == 1 else "s", rname)
        tier = src.get("tier") or ("fast" if worst["severity"] == "high" or worst["agreed"] else "small")
        j = st.new_job(p["id"], title, tier=tier, source="evaluator:%s/%s" % (os.path.basename(folder), rname),
                       key="eval:%s:%s:%s" % (folder, rname, jid), stream=p["stream"], runner=src.get("runner", "auto"),
                       batch="eval-%s-%s" % (os.path.basename(folder), rname),
                       done=done_checks(p, ["Each finding below is fixed and visible in the product"]),
                       context="Review findings for journey %s, ranked (agreed by every reviewer first):\n- %s\n"
                               "Then write the next round's changes.md in %s (one bullet per change)." % (
                                   jid, "\n- ".join(lines), folder))
        apply_needs(j, p)
        jobs.append(j)
    return jobs, ""


# ---------------------------------------------------------------- failing tests

def jobs_from_tests(p, src):
    cmd = src.get("command") or p.get("test")
    if not cmd:
        return [], "no test command for %s" % p["id"]
    try:
        r = subprocess.run(["sh", "-c", cmd], cwd=p["path"], capture_output=True, text=True, timeout=int(src.get("timeout", 900)))
    except (OSError, subprocess.SubprocessError) as e:
        return [], "could not run the tests: %s" % e
    if r.returncode == 0:
        return [], ""
    tail = "\n".join((r.stdout + "\n" + r.stderr).strip().splitlines()[-40:])
    job = st.new_job(p["id"], "Make the tests pass (%s)" % cmd, tier=src.get("tier", "fast"),
                     done=["The tests pass::%s" % cmd], source="tests", key="tests:%s" % cmd, stream=p["stream"],
                     runner=src.get("runner", "auto"), files=mentioned_files(tail, p["path"]),
                     context="The test command exited %d. The last lines of its output:\n%s" % (r.returncode, tail))
    apply_needs(job, p)
    return [job], ""


# ---------------------------------------------------------------- daily jobs

def jobs_from_daily(p, src, today):
    jid = src.get("id") or re.sub(r"[^a-z0-9]+", "-", src.get("title", "daily").lower()).strip("-")
    job = st.new_job(p["id"], src.get("title") or jid, outcome=src.get("outcome", ""), tier=src.get("tier", "fast"),
                     estimate=src.get("estimate_tokens"), unattended=src.get("unattended", True),
                     files=src.get("files", []), runner=src.get("runner", "auto"), source="daily:%s" % jid,
                     key="daily:%s:%s" % (jid, today), stream=p["stream"], context=src.get("prompt", ""),
                     done=list(src.get("done") or ["The output of this daily job is in the project as a draft"]))
    job["not_before"] = "%sT%s" % (today, src.get("at", "00:00"))
    apply_needs(job, p)
    return [job], ""


# ---------------------------------------------------------------- the scan

def scan(cfg, q, only=None, run_tests=True):
    """Turn every project's sources into jobs. Returns a report of what was added and what could not be read."""
    today = st.now().date().isoformat()
    report = {"added": [], "notes": []}
    for p in cfg["projects"]:
        if only and p["id"] != only:
            continue
        if not os.path.isdir(p["path"]):
            report["notes"].append("%s: folder not found: %s" % (p["id"], p["path"]))
            continue
        for src in p.get("sources", []):
            kind = src.get("kind")
            if kind == "plan":
                jobs, note = jobs_from_plan(p, src)
            elif kind == "evaluator":
                jobs, note = jobs_from_evaluator(p, src)
            elif kind == "tests":
                jobs, note = jobs_from_tests(p, src) if run_tests else ([], "")
            elif kind == "daily":
                jobs, note = jobs_from_daily(p, src, today)
            else:
                jobs, note = [], "%s: unknown source kind %r" % (p["id"], kind)
            if note:
                report["notes"].append("%s: %s" % (p["id"], note))
            for j in jobs:
                if st.add_job(q, j):
                    report["added"].append({"id": j["id"], "title": j["title"], "tier": j["tier"], "source": j["source"]})
    return report
