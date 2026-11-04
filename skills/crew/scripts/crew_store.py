#!/usr/bin/env python3
"""crew's private state: the config, the queue of jobs, the switches, and the rules about when a job may run.

Everything lives in ~/.mstack/crew (or $MSTACK_HOME/crew), outside any repository. Python 3.9 or later,
standard library only. Nothing here talks to a model or the network.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
TIERS = ("small", "fast", "top")
STATES = ("todo", "doing", "done", "question", "blocked", "failed", "skipped")
RUNNERS = ("claude", "codex")

DEFAULTS = {
    "reserve_percent": 15,                       # the person's share of every usage window; crew never touches it
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "heavy_tokens": 200000,                      # a job estimated above this, or on the top tier, is heavy
    "usage_max_age_minutes": 90,                 # older readings are stale; a probe is allowed when stale
    "probe": True,                               # a one word call to read a window when no fresh reading exists
    "conservative": {"jobs_per_day": 3},         # when a runner's usage cannot be read: overnight only, this many a day
    "digest": {"at": "07:00"},
    "tick_minutes": 15,
    "runners": {
        "claude": {"command": ["claude", "-p"], "models": {"small": "haiku", "fast": "sonnet", "top": "opus"},
                   "probe_model": "haiku"},
        "codex": {"command": ["codex", "exec"], "models": {}},
    },
    "projects": [],
}


def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, "crew", *parts)


def mstack_config():
    path = os.path.join(os.path.dirname(home()), "config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return {}


def crew_is_on():
    return "crew" not in mstack_config().get("disabled", [])


def now():
    return datetime.datetime.now()


def stamp(dt=None):
    return (dt or now()).isoformat(timespec="seconds")


def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)                        # never half written, even on a crash


def merge(base, mine):
    out = json.loads(json.dumps(base))
    for k, v in (mine or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = merge(DEFAULTS, read_json(home("config.json"), {}))
    for p in cfg["projects"]:
        p.setdefault("id", os.path.basename(p.get("path", "").rstrip("/")) or "project")
        p.setdefault("stream", "work")
        p.setdefault("mode", "branch")           # branch: a side branch in its own worktree; in_place: no commits
        p.setdefault("sources", [])
        p.setdefault("github", False)
        p.setdefault("path", "")
        p["path"] = os.path.expanduser(p["path"])
    return cfg


def project(cfg, pid):
    for p in cfg["projects"]:
        if p["id"] == pid:
            return p
    raise SystemExit("No crew project %r. The projects are: %s" % (pid, ", ".join(p["id"] for p in cfg["projects"]) or "none"))


# ---------------------------------------------------------------- the queue

def load_queue():
    return read_json(home("queue.json"), {"jobs": [], "questions": []})


def save_queue(q):
    write_json(home("queue.json"), q)


def load_state():
    return read_json(home("state.json"), {"paused": False, "running": [], "daily": {}, "digest_sent": ""})


def save_state(s):
    write_json(home("state.json"), s)


def job_id(pid, key):
    return "%s-%s" % (pid, hashlib.sha1(key.encode("utf-8")).hexdigest()[:6])


def new_job(pid, title, outcome="", done=None, tier="fast", estimate=None, unattended=True, files=None,
            runner="auto", source="manual", key=None, stream="", context="", batch=""):
    key = key or title
    tier = tier if tier in TIERS else "fast"
    return {"id": job_id(pid, key), "project": pid, "stream": stream, "title": title.strip(),
            "outcome": (outcome or title).strip(), "done": list(done or []), "tier": tier,
            "estimate_tokens": int(estimate if estimate is not None else {"small": 40000, "fast": 120000, "top": 400000}[tier]),
            "unattended": bool(unattended), "files": list(files or []), "runner": runner, "source": source,
            "key": key, "batch": batch, "context": context, "state": "todo", "created": stamp(), "started": "",
            "finished": "", "evidence": [], "usage": {}, "question": "", "default": "", "note": "", "tries": 0}


def add_job(q, job):
    """Add a job unless one with the same id is already queued, running or finished. Returns True when added."""
    if any(j["id"] == job["id"] for j in q["jobs"]):
        return False
    q["jobs"].append(job)
    return True


def find_job(q, jid):
    for j in q["jobs"]:
        if j["id"] == jid:
            return j
    raise SystemExit("No crew job %r. Run: list" % jid)


def is_heavy(cfg, job):
    return job["tier"] == "top" or job["estimate_tokens"] >= int(cfg.get("heavy_tokens", 200000))


# ---------------------------------------------------------------- time, quiet hours, away

def parse_hhmm(text):
    h, m = str(text).split(":")[:2]
    return int(h) * 60 + int(m)


def is_quiet(cfg, at=None):
    """True inside the quiet hours (which may span midnight), when the person is not using their own sessions."""
    q = cfg.get("quiet_hours") or {}
    if not q.get("start") or not q.get("end"):
        return False
    t = at or now()
    cur, start, end = t.hour * 60 + t.minute, parse_hhmm(q["start"]), parse_hhmm(q["end"])
    return start <= cur < end if start <= end else (cur >= start or cur < end)


def person_is_away():
    """Ask away-mode. Only a clear "away" counts; unsure means present, the safe side for a heavy job."""
    if os.environ.get("MSTACK_CREW_AWAY") in ("0", "1"):          # for tests
        return os.environ["MSTACK_CREW_AWAY"] == "1"
    tool = os.path.join(SKILLS, "away-mode", "scripts", "away.py")
    if not os.path.exists(tool):
        return False
    try:
        r = subprocess.run([sys.executable, tool, "status"], capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout or "{}").get("away") is True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def heavy_ok(cfg, at=None):
    return is_quiet(cfg, at) or person_is_away()


# ---------------------------------------------------------------- switches and locks

def stop_file():
    return home("stop")


def stopped():
    """Why crew must not run right now, or an empty string when it may."""
    if os.path.exists(stop_file()):
        return "the stop file exists (%s); remove it or run: crew.py go" % stop_file()
    if not crew_is_on():
        return "crew is switched off in mStack's config.json (mstack.py enable crew turns it on)"
    if load_state().get("paused"):
        return "crew is paused (crew.py resume)"
    return ""


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def take_tick_lock():
    """One tick at a time. Returns True when this process holds the lock."""
    path = home("tick.lock")
    old = read_json(path, {})
    if old.get("pid") and pid_alive(old["pid"]) and old["pid"] != os.getpid():
        return False
    write_json(path, {"pid": os.getpid(), "at": stamp()})
    return True


def release_tick_lock():
    try:
        os.remove(home("tick.lock"))
    except OSError:
        pass


def running_jobs(state, q):
    """Jobs recorded as running whose process is still alive; the rest are cleaned up as failed."""
    alive = []
    for r in state.get("running", []):
        if pid_alive(r.get("pid")):
            alive.append(r)
        else:
            for j in q["jobs"]:
                if j["id"] == r["job"] and j["state"] == "doing":
                    j["state"] = "failed"
                    j["note"] = "the runner process disappeared without a result"
                    j["finished"] = stamp()
    state["running"] = alive
    return alive


def files_clash(job, running, q):
    """True when a running job touches the same project, or any of the same files, as this one."""
    mine = set(os.path.normpath(f) for f in job.get("files", []))
    for r in running:
        other = next((j for j in q["jobs"] if j["id"] == r["job"]), None)
        if not other:
            continue
        if other["project"] == job["project"]:
            return True
        if mine & set(os.path.normpath(f) for f in other.get("files", [])):
            return True
    return False


def git(path, *args, check=False):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:300]))
    return r.stdout.strip()


def have(program):
    return shutil.which(program) is not None
