"""Where `mstack status` finds projects and what it reads from each one. Python 3.9 or later, standard library only.

A project is one absolute folder. It is found from the rules files, the outcomes, the crew config and queue, and
the multi-evaluator folders under the mStack home. Nothing here writes anything.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
for _skill in ("outcome-first", "crew", "multi-evaluator", "away-mode"):
    _dir = os.path.join(SKILLS, _skill, "scripts")
    if _dir not in sys.path:
        sys.path.insert(1, _dir)        # ahead of site-packages, which has an unrelated "outcome"
EVAL_NAME = "mstack-eval.json"


def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, *parts)


def tool(skill, name):
    return "python3 " + shlex.quote(os.path.join(SKILLS, skill, "scripts", name))


def norm(path):
    return os.path.realpath(os.path.expanduser(str(path)))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def recent(stamp, days):
    """True when an ISO date or time is within the last `days` days (an unreadable one counts as recent)."""
    try:
        when = datetime.datetime.fromisoformat(str(stamp)[:19])
    except ValueError:
        return True
    return (datetime.datetime.now() - when).total_seconds() <= days * 86400


# ---------------------------------------------------------------- finding projects

def review_folders():
    found = []
    for top in ("reviews", "private-reviews"):
        base = home(top)
        for root, dirs, files in os.walk(base):
            if EVAL_NAME in files:
                found.append(root)
                dirs[:] = []
            elif root[len(base):].count(os.sep) >= 3:
                dirs[:] = []
    return sorted(found)


def collect():
    """{path: record}, every project from every source, merged by folder (a folder inside another belongs to it)."""
    refs = []
    projects = home("projects")
    for slug in sorted(os.listdir(projects)) if os.path.isdir(projects) else []:
        meta = read_json(os.path.join(projects, slug, "project.json")) or {}
        if meta.get("path"):
            refs.append((meta["path"], "rules", {"slug": slug}))
    outcomes = home("outcomes")
    for slug in sorted(os.listdir(outcomes)) if os.path.isdir(outcomes) else []:
        o = read_json(os.path.join(outcomes, slug, "outcome.json"))
        if o and o.get("cwd"):
            refs.append((o["cwd"], "outcome", dict(o, slug=slug)))
    crew = {"cfg": None, "queue": {"jobs": [], "questions": []}, "loose": []}
    if os.path.exists(home("crew", "config.json")):
        import crew_store as cst
        crew["cfg"], crew["queue"] = cst.load_config(), cst.load_queue()
        ids = dict((p["id"], p["path"]) for p in crew["cfg"]["projects"] if p.get("path"))
        for pid, path in ids.items():
            refs.append((path, "crew project", {"id": pid}))
        for j in crew["queue"]["jobs"]:
            if j.get("project") in ids:
                refs.append((ids[j["project"]], "crew job", j))
        for x in crew["queue"]["questions"]:
            job = next((j for j in crew["queue"]["jobs"] if j["id"] == x.get("job")), {})
            pid = x.get("project") or job.get("project")
            if not x.get("answer") and pid in ids:
                refs.append((ids[pid], "crew question", x))
            elif not x.get("answer"):
                crew["loose"].append(x)             # for example the ask to keep going past the reserve
    for folder in review_folders():
        cfg = read_json(os.path.join(folder, EVAL_NAME)) or {}
        parent = os.path.dirname(folder)
        if cfg.get("project"):
            where = cfg["project"]
        elif parent in (home("reviews"), home("private-reviews")):
            where = folder
        else:
            where = parent
        refs.append((where, "review", {"folder": folder, "name": cfg.get("name", os.path.basename(folder))}))
    paths = set(norm(p) for p, _, _ in refs)
    records = {}
    for path, kind, data in refs:
        full = norm(path)
        above = [q for q in paths if full.startswith(q + os.sep)]
        root = min(above, key=len) if above else full
        rec = records.setdefault(root, {"path": root, "name": os.path.basename(root) or root, "outcomes": [], "jobs": [],
                                        "questions": [], "reviews": [], "kinds": []})
        rec["kinds"].append(kind)
        key = {"outcome": "outcomes", "crew job": "jobs", "crew question": "questions", "review": "reviews"}.get(kind)
        if key:
            rec[key].append(data)
    return records, crew


# ---------------------------------------------------------------- what each project has

def waits_for(rec, crew_cmd):
    import outcome
    out = []
    for o in rec["outcomes"]:
        if o.get("achieved"):
            continue
        for q in outcome.open_questions(o):
            default = " (default: %s)" % q["default"] if q.get("default") else ""
            out.append({"kind": "outcome question", "text": "%s asks: %s%s" % (o["slug"], q["text"], default),
                        "command": '%s answer %s %s "..."' % (tool("outcome-first", "outcome.py"), o["slug"], q["id"])})
        if outcome.state_of(o) == "blocked":
            blocked = [t["id"] + " " + t["title"] for t in o["tasks"] if t["state"] == "blocked"]
            out.append({"kind": "outcome blocked", "text": "%s is blocked: %s" % (o["slug"], ", ".join(blocked)),
                        "command": "%s status %s" % (tool("outcome-first", "outcome.py"), o["slug"])})
    for x in rec["questions"]:
        default = " (default: %s)" % x["default"] if x.get("default") else ""
        out.append({"kind": "crew question", "text": "crew asks: %s%s" % (x.get("question", ""), default),
                    "command": '%s answer %s "..."' % (crew_cmd, x.get("job") or x["key"])})
    for r in review_info(rec, None):
        if r["waiting"]:
            out.append({"kind": "review", "text": "%s: round %d has every verdict and is not ready, so the fixes are yours" % (
                r["name"], r["round"]), "command": "%s status --dir %s" % (tool("multi-evaluator", "eval_loop.py"), shlex.quote(r["folder"]))})
    return out


def running_for(rec, days):
    out = []
    for j in rec["jobs"]:
        if j.get("state") == "doing":
            out.append("crew job: %s (%s, started %s)" % (j["title"], j.get("runner_used") or j.get("runner", "?"),
                                                           (j.get("started") or "?")[:16].replace("T", " ")))
    for o in rec["outcomes"]:
        if not o.get("achieved") and recent(o.get("updated", ""), days):
            for t in o["tasks"]:
                if t["state"] == "doing":
                    out.append("outcome %s, doing: %s" % (o["slug"], t["title"]))
    return out


def review_info(rec, days):
    """One entry per review folder: the newest round, whether it is ready, the overall scores, and whether it waits."""
    out = []
    try:
        import eval_loop
        import readiness
    except ImportError:
        return out
    for r in rec["reviews"]:
        try:
            p = eval_loop.Project(r["folder"])
            n = p.latest()
            if not n:
                continue
            rs = readiness.round_state(p, n)
            stamp = datetime.datetime.fromtimestamp(os.path.getmtime(p.rdir(n))).isoformat(timespec="seconds")
            out.append({"name": r["name"], "folder": r["folder"], "round": n, "updated": stamp,
                        "ready": bool(readiness.ready_for_people(p)["ready"]), "round_passes": bool(rs["ready"]),
                        "overall": dict((k, v) for k, v in rs["overall"].items() if v is not None),
                        "waiting": bool(rs["verdicts"]) and not rs["missing_verdicts"] and not rs["ready"]
                        and rs["shots"] > 0, "recent": days is None or recent(stamp, days)})
        except (SystemExit, Exception):
            continue
    return out


def latest_review(rec, days):
    rows = [r for r in review_info(rec, days) if r["recent"]]
    return max(rows, key=lambda r: r["updated"]) if rows else None


def shipped(path):
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=30)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    tag = git("for-each-ref", "--sort=-creatordate", "--format", "%(refname:short) %(creatordate:short)", "refs/tags")
    if tag:
        name, _, date = tag.splitlines()[0].partition(" ")
        return "%s, %s" % (name, date)
    day = git("log", "-1", "--format=%cs")
    return "last commit %s" % day if day else None


def state_lines(path):
    try:
        with open(os.path.join(path, "HANDOFF.md"), encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out, inside = [], False
    for line in lines:
        if line.strip().lower() == "## state":
            inside = True
        elif inside and line.startswith("#"):
            break
        elif inside and line.strip():
            out.append(line.strip())
    return out[:3]


def usage_block():
    if not os.path.exists(home("crew", "config.json")):
        return {"crew": False}
    import crew_store as cst
    import crew_usage
    cfg, q = cst.load_config(), cst.load_queue()
    runners = {}
    for r in cst.RUNNERS:
        b = crew_usage.runner_budget(cfg, r, q, False)
        runners[r] = {"mode": b["mode"], "why": b["why"], "headroom": b["headroom"],
                      "windows": (b["reading"] or {}).get("windows", [])}
    digests = home("crew", "digests")
    files = sorted(f for f in os.listdir(digests) if f.endswith(".html")) if os.path.isdir(digests) else []
    return {"crew": True, "stopped": cst.stopped(), "quiet_now": cst.is_quiet(cfg), "runners": runners,
            "last_digest": os.path.join(digests, files[-1]) if files else ""}
