"""Which reviewers can run, and what happens when one hits its usage limit partway through a round.

Used by eval_loop.py (preflight, brief, review, choose, status), readiness.py and report.py. Standard library only.

Preflight checks every enabled reviewer before a round: its program is found, it is signed in, and how much of
its plan's usage is left with the reset time. Usage numbers come from the crew skill's crew_usage.py, which reads
real windows (Claude Code's rate_limit_event, Codex's session log). A number that cannot be read is reported as
"unknown", never guessed.

A reviewer that hits its usage limit is recorded as paused (rounds/r<N>/availability/<id>.paused.json), not as a
broken reply. Then the readiness rule decides: if at least two counting reviewers from different makers are left,
the round goes on without the paused one and is marked short one reviewer. If not, the round stops and the person
chooses (choose --choice): wait until the reset, use the paused reviewer's configured backup, or run with fewer
reviewers, labelled as not counting toward ready for people. The tool never waits on its own.
"""
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CREW = os.path.join(os.path.dirname(os.path.dirname(HERE)), "crew", "scripts")

LIMIT_PERCENT = 99        # a window this full means the reviewer cannot run until it resets
NEAR_PERCENT = 90         # this full: it runs, with a warning that it may stop partway
CHOICES = ("wait", "backup", "fewer")
SIGNIN_TIMEOUT = 20

LIMIT_RE = re.compile(
    r"usage limit|rate[ _-]?limit(?:ed| reached| exceeded)|limit reached|hit your (?:usage |session |weekly )?limit|"
    r"quota (?:exceeded|reached)|insufficient_quota|exceeded your (?:current )?quota|out of (?:credits|usage)|"
    r"too many requests|usage cap|reached your (?:usage |plan )?limit", re.I)


# ---------------------------------------------------------------- small helpers

def stamp():
    return datetime.datetime.now().isoformat(timespec="seconds")


def when(ts):
    """A reset time in plain words, in local time, for example "15:00 on 13 Nov"."""
    if not ts:
        return "unknown"
    t = datetime.datetime.fromtimestamp(int(ts))
    return "%s on %d %s" % (t.strftime("%H:%M"), t.day, t.strftime("%b"))


def adir(p, n, *parts):
    return p.rdir(n, "availability", *parts)


def program_of(cmd):
    if not cmd:
        return None
    if isinstance(cmd, str):
        if re.search(r"[&|;<>$`()=]", cmd):
            return None
        try:
            cmd = shlex.split(cmd)
        except ValueError:
            return None
    return cmd[0] if cmd else None


def runner_for(r):
    """Whose usage this reviewer spends: the reviewer's "usage" field ("claude", "codex" or "none"), else the
    program its command starts (claude or codex). None when that cannot be told."""
    if "usage" in r:
        return None if r["usage"] in (None, "", "none") else r["usage"]
    prog = program_of(r.get("command"))
    base = os.path.basename(prog) if prog else ""
    return base if base in ("claude", "codex") else None


def _crew_usage():
    if CREW not in sys.path:
        sys.path.insert(0, CREW)
    try:
        import crew_usage  # noqa: E402
        return crew_usage
    except Exception:
        return None


def usage_reading(runner, probe=False):
    """{"percent", "window", "resets_at", "resets", "read", "minutes_old"} from crew_usage, or None when it cannot be
    read. probe=True allows one tiny Claude call to read the windows (it costs a little usage)."""
    cu = _crew_usage()
    if not cu or not runner:
        return None
    cfg = {"usage_max_age_minutes": 90, "probe": bool(probe), "runners": {"claude": {}}}
    try:
        reading = cu.fresh_reading(cfg, runner, allow_probe=bool(probe))
    except Exception:
        return None
    if not reading or not reading.get("windows"):
        return None
    w = max(reading["windows"], key=lambda x: x.get("percent", 0))
    return {"percent": w.get("percent"), "window": (w.get("window") or "").replace("_", " "),
            "resets_at": w.get("resets_at") or None, "resets": when(w.get("resets_at")),
            "read": reading.get("how", ""), "minutes_old": int(round(cu.age_minutes(reading)))}


def signin_command(r, prog):
    if r.get("signin_check"):
        return r["signin_check"], "exit"
    base = os.path.basename(prog or "")
    if base == "claude":
        return [prog, "auth", "status"], "claude"
    if base == "codex":
        return [prog, "login", "status"], "text"
    if base in ("cursor-agent", "agent"):
        return [prog, "status"], "text"
    return None, None


def signed_in(r, prog):
    """True, False, or "unknown". Only a yes or no is kept: the check's own output (it may name the account) is
    never stored."""
    cmd, how = signin_command(r, prog)
    if not cmd:
        return "unknown"
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=SIGNIN_TIMEOUT, stdin=subprocess.DEVNULL,
                             shell=isinstance(cmd, str))
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = (out.stdout or "") + (out.stderr or "")
    if how == "exit":
        return out.returncode == 0
    if how == "claude":
        try:
            data = json.loads(out.stdout)
            if isinstance(data.get("loggedIn"), bool):
                return data["loggedIn"]
        except (ValueError, AttributeError):
            pass
    if re.search(r"not (?:logged|signed) in|logged out|signed out|please (?:log|sign) in", text, re.I):
        return False
    if re.search(r"\b(?:logged|signed) in\b", text, re.I) and out.returncode == 0:
        return True
    return "unknown"


# ---------------------------------------------------------------- preflight

def check_reviewer(r, probe=False, signin=True):
    """One reviewer before a round. state: ready, paused (usage limit), missing (program not found), signed out,
    or by-agent (the person's own agent runs it, nothing to start)."""
    kind = r.get("kind", "agent")
    out = {"id": r["id"], "name": r.get("name", r["id"]), "kind": kind, "maker": r.get("maker"),
           "program": None, "found": None, "signed_in": "not checked", "usage": "unknown", "state": "ready",
           "will_run": True, "why": ""}
    if r.get("backup"):
        out["backup"] = r["backup"]
    prog = program_of(r.get("command")) if kind == "command" else None
    if kind == "command":
        out["program"] = prog or "(a shell line)"
        path = shutil.which(prog) if prog else None
        out["found"] = bool(path) if prog else "unknown"
        if prog and not path:
            out.update(state="missing", will_run=False,
                       why="the program %s was not found: install it, or set this reviewer's command to its full path" % prog)
            return out
        if signin:
            out["signed_in"] = signed_in(r, path or prog)
        if out["signed_in"] is False:
            out.update(state="signed out", will_run=False,
                       why="%s is not signed in: sign in to it, then run preflight again" % (prog or out["name"]))
            return out
    runner = runner_for(r)
    reading = usage_reading(runner, probe) if runner else None
    if reading:
        out["usage"] = reading
        pct = reading["percent"] or 0
        future = reading["resets_at"] and reading["resets_at"] > time.time()
        if pct >= LIMIT_PERCENT and future:
            out.update(state="paused", will_run=False,
                       why="usage limit: its %s window is at %s%%, resets at %s" % (reading["window"], pct, reading["resets"]))
            return out
        if pct >= NEAR_PERCENT:
            out["why"] = "runs, but its %s window is at %s%% and may run out partway (resets at %s)" % (
                reading["window"], pct, reading["resets"])
    elif runner:
        out["why"] = "usage left is unknown: no reading for %s on this computer%s" % (
            runner, "" if probe else " (preflight --probe reads Claude's with one tiny call)")
    else:
        out["why"] = "usage left is unknown: set \"usage\" (claude or codex) on this reviewer if it spends one of those plans"
    if kind != "command":
        out["state"] = "by-agent" if out["state"] == "ready" else out["state"]
        out["why"] = ("your own agent runs this reviewer. " + out["why"]).strip()
    return out


def preflight(p, probe=False, signin=True, reviewers=None):
    rs = reviewers if reviewers is not None else p.enabled_reviewers()
    checks = [check_reviewer(r, probe=probe, signin=signin) for r in rs]
    blocked = [c for c in checks if not c["will_run"]]
    return {"checked": stamp(), "reviewers": checks, "will_not_run": [c["id"] for c in blocked],
            "summary": ("every reviewer can run" if not blocked else "will not run: " + "; ".join(
                "%s (%s)" % (c["id"], c["why"]) for c in blocked))}


def preflight_text(data):
    lines = []
    for c in data["reviewers"]:
        u = c["usage"]
        usage = ("%s%% of %s, resets %s (read %d min ago)" % (u["percent"], u["window"], u["resets"], u["minutes_old"])
                 if isinstance(u, dict) else "unknown")
        lines.append("%-12s %-10s found %-7s signed in %-11s usage %s" % (
            c["id"], c["state"], {True: "yes", False: "no", None: "n/a"}.get(c["found"], c["found"]),
            {True: "yes", False: "no"}.get(c["signed_in"], c["signed_in"]), usage))
        if c["why"]:
            lines.append("             " + c["why"])
    lines.append(data["summary"])
    return "\n".join(lines)


# ---------------------------------------------------------------- spotting a usage limit in a failed run

def limit_in_text(text):
    """{"resets_at", "resets", "evidence"} when the text carries a usage limit message, else None."""
    if not text:
        return None
    m = LIMIT_RE.search(text)
    if not m:
        return None
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end = text.find("\n", m.end())
    evidence = text[line_start:line_end if line_end >= 0 else None].strip()[:200]
    resets_at, resets = None, ""
    ts = re.search(r"limit reached\|(\d{9,11})", text, re.I)
    rel = re.search(r"(?:try again|resets?|available again) in\s+(?:(\d+)\s*h(?:ours?|rs?)?)?[\s,and]*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?",
                    text, re.I)
    at = re.search(r"(?:try again|resets?|available again)\s+(?:at\s+)?([0-9][^\n.;,]{0,30}|(?:mon|tue|wed|thu|fri|sat|sun)[^\n.;,]{0,30})",
                   text, re.I)
    if ts:
        resets_at = int(ts.group(1))
    elif rel and (rel.group(1) or rel.group(2)):
        resets_at = int(time.time() + 3600 * int(rel.group(1) or 0) + 60 * int(rel.group(2) or 0))
    elif at:
        resets = at.group(1).strip()
    return {"resets_at": resets_at, "resets": when(resets_at) if resets_at else (resets or "unknown"), "evidence": evidence}


def classify_failure(r, raw, err, timed_out=False):
    """A failed run is a usage limit when its reply or errors say so, or when the reviewer's usage reading is at or
    near 100%. Returns the pause record (without round details) or None."""
    hit = limit_in_text((raw or "") + "\n" + (err or ""))
    reading = usage_reading(runner_for(r))
    if hit:
        if not hit["resets_at"] and reading and reading.get("resets_at"):
            hit.update(resets_at=reading["resets_at"], resets=reading["resets"])
        hit["source"] = "the reviewer's reply"
        return hit
    if reading and (reading["percent"] or 0) >= LIMIT_PERCENT - 4:
        return {"resets_at": reading["resets_at"], "resets": reading["resets"], "source": "usage reading",
                "evidence": "%s window at %s%%%s" % (reading["window"], reading["percent"], " after a timeout" if timed_out else "")}
    return None


def record_pause(p, n, rid, info):
    os.makedirs(adir(p, n), exist_ok=True)
    rec = {"reviewer": rid, "round": n, "state": "paused", "reason": "usage limit", "at": stamp(),
           "resets_at": info.get("resets_at"), "resets": info.get("resets") or "unknown",
           "source": info.get("source", ""), "evidence": info.get("evidence", "")}
    rec["label"] = "paused: usage limit, resets at %s" % rec["resets"]
    with open(adir(p, n, rid + ".paused.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    return rec


# ---------------------------------------------------------------- the round's plan

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def paused(p, n):
    """Pause records for reviewers that still have no verdict this round."""
    d = adir(p, n)
    if not os.path.isdir(d):
        return []
    have = set(p.verdicts(n))
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".paused.json") and f[:-len(".paused.json")] not in have:
            rec = read_json(os.path.join(d, f))
            if rec:
                out.append(rec)
    return out


def choice(p, n):
    return read_json(adir(p, n, "choice.json"))


def standins(p, n):
    """{paused reviewer id: backup id} once the person chose the backup for round n."""
    c = choice(p, n) or {}
    return dict(c.get("standins") or {}) if c.get("choice") == "backup" else {}


def maker_key(p, rid):
    r = p.reviewer(rid) or {}
    return (r.get("maker") or "").strip().lower() or "reviewer:" + rid


def plan(p, n):
    """What round n can still do. The readiness rule: at least two counting reviewers from different makers."""
    import readiness
    ps = paused(p, n)
    ids = [x["reviewer"] for x in ps]
    stand = standins(p, n)
    kinds = dict((r["id"], r.get("kind")) for r in p.reviewers())
    roster = readiness.round_reviewers(p, n)
    left = [rid for rid in roster if rid not in ids and kinds.get(rid) != "chat"]
    makers = sorted(set(maker_key(p, rid) for rid in left))
    enough = len(left) >= 2 and len(makers) >= 2
    c = choice(p, n)
    picked = c.get("choice") if c else None
    resets = [x["resets_at"] for x in ps if x.get("resets_at")]
    latest = max(resets) if resets and len(resets) == len(ps) else None
    backups = {}
    for rid in ids:
        b = (p.reviewer(rid) or {}).get("backup")
        if b and p.reviewer(b) and b not in ids and b not in roster:
            backups[rid] = b
    out = {"round": n, "paused": ps, "counting_left": left, "makers_left": [m for m in makers if not m.startswith("reviewer:")],
           "enough": enough, "short": bool(ps), "choice": picked, "standins": stand,
           "choice_needed": bool(ps) and not enough and picked is None,
           "skip": ids if (ps and (enough or picked in ("backup", "fewer"))) else [],
           "counts_toward_ready": not (picked == "fewer" and ps)}
    if ps:
        out["label"] = "; ".join("%s %s" % (x["reviewer"], x["label"]) for x in ps)
    if out["choice_needed"]:
        wait_detail = ("until %s" % when(latest)) if latest else "until the limit resets (the time is unknown)"
        out["choices"] = [
            {"id": "wait", "available": True,
             "detail": "wait %s, then run the paused reviewer%s again: review --round %d --only %s" % (
                 wait_detail, "" if len(ids) == 1 else "s", n, ",".join(ids))},
            {"id": "backup", "available": len(backups) == len(ids),
             "detail": ("use the configured backup%s (%s) in %s place" % (
                 "" if len(backups) == 1 else "s", ", ".join("%s for %s" % (b, a) for a, b in backups.items()),
                 "its" if len(ids) == 1 else "their"))
             if len(backups) == len(ids) else
             "no backup is configured for %s (add \"backup\": \"<another reviewer's id>\" to it)" % ", ".join(
                 rid for rid in ids if rid not in backups)},
            {"id": "fewer", "available": True,
             "detail": "finish the round with %s only; it is labelled as not counting toward ready for people" % (
                 ", ".join(left) or "no counting reviewer")},
        ]
        out["question"] = ("%s hit %s usage limit (resets %s), which leaves fewer than two counting reviewers from "
                           "different makers. Wait for the reset, use a backup reviewer, or run this round with fewer "
                           "reviewers (it will not count toward ready for people)?" % (
                               " and ".join(ids), "its" if len(ids) == 1 else "their",
                               ", ".join("%s %s" % (x["reviewer"], x["resets"]) for x in ps) if len(ps) > 1 else ps[0]["resets"]))
        out["how_to_answer"] = "choose --round %d --choice wait|backup|fewer" % n
    return out


def save_choice(p, n, picked):
    pl = plan(p, n)
    if not pl["paused"]:
        raise SystemExit("No reviewer is paused in round %d, so there is nothing to choose." % n)
    if picked not in CHOICES:
        raise SystemExit("--choice is one of: %s" % ", ".join(CHOICES))
    rec = {"choice": picked, "at": stamp(), "paused": [x["reviewer"] for x in pl["paused"]]}
    if picked == "backup":
        stand = {}
        for x in pl["paused"]:
            b = (p.reviewer(x["reviewer"]) or {}).get("backup")
            if not b or not p.reviewer(b):
                raise SystemExit("%s has no backup reviewer in the config: add \"backup\": \"<id of another reviewer>\" "
                                 "to it, or choose wait or fewer." % x["reviewer"])
            stand[x["reviewer"]] = b
        rec["standins"] = stand
    os.makedirs(adir(p, n), exist_ok=True)
    with open(adir(p, n, "choice.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    return rec


def roster(p, n):
    """The reviewers that run in round n: every enabled one, plus backups standing in for paused ones."""
    rs = list(p.enabled_reviewers())
    have = set(r["id"] for r in rs)
    for b in standins(p, n).values():
        r = p.reviewer(b)
        if r and b not in have:
            rs.append(r)
            have.add(b)
    return rs
