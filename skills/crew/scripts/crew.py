#!/usr/bin/env python3
"""crew: useful work running in the background all the time, within the usage the person already pays for,
so they are taken out of every job they do not need to be in. One queue across projects; the cheapest model
that fits each job; the person's 15% of every usage window kept; drafts and side branches only.

Python 3.9 or later, standard library only. State lives in ~/.mstack/crew (or $MSTACK_HOME/crew). Every
command prints JSON with --json (status, next, usage and list print JSON by default), so any agent can drive it.

  init                                 write a starter config.json (does nothing if one exists)
  scan [--project ID] [--no-tests]     turn every project's sources (plan, evaluator, tests, daily) into jobs
  add <project> "<title>" [--outcome ...] [--done "what::command"] [--tier small|fast|top] [--file F] [--runner R]
  list [--all]                         the queue (todo and running by default)
  next                                 the job that would run now, and why others would not
  run [<job-id>] [--dry-run]           run one job now (the next eligible one by default)
  tick [--max N]                       what the background job calls: scan, budget, run, digest when due
  branches [--project ID] [--prune]    list the crew/* side branches (job, status, commits ahead, merged); --prune
                                       deletes only the merged or empty ones, never one with unmerged work
  status                               where crew stands: switches, usage, queue, questions, the next step
  usage [--probe]                      each runner's windows, measured; --probe allows a one word read
  digest [--no-send]                   the morning digest now (HTML, PDF, phone PNG, ping)
  answer <job-id or key> "<answer>"    answer a question (a job's, or the ask to continue past the reserve)
  retry <job-id> | drop <job-id>       put a blocked or failed job back once, or remove a job
  pause | resume                       hold every job without uninstalling
  stop | go                            the stop file: nothing runs while it exists
  install [--every 15] [--dry-run]     the background job (launchd, cron, systemd notes, Task Scheduler notes)
  uninstall [--dry-run]
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_SKILLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOCKS = os.path.join(_SKILLS, "mstack", "scripts")
if _LOCKS not in sys.path:
    sys.path.insert(0, _LOCKS)
import locks  # noqa: E402
import crew_branches as branches  # noqa: E402
import crew_digest as digest   # noqa: E402
import crew_install as inst    # noqa: E402
import crew_run as runner      # noqa: E402
import crew_sources as sources # noqa: E402
import crew_store as st        # noqa: E402
import crew_usage as usage     # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(st.HERE), "templates", "config.json")
ORDER = {"tests": 0, "daily": 1, "evaluator": 2, "plan": 3, "manual": 2}


def out(args, data, text=None):
    if getattr(args, "json", False) or text is None:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(text)


# ---------------------------------------------------------------- eligibility

def budgets_for(cfg, q, allow_probe):
    return dict((r, usage.runner_budget(cfg, r, q, allow_probe)) for r in st.RUNNERS)


def why_not(cfg, q, state, job, budgets, running):
    """An empty string when the job may run now, else the reason it waits."""
    if job["state"] != "todo":
        return "state is %s" % job["state"]
    ra = job.get("retry_after")
    if ra and ra > st.stamp():
        return "retry at %s" % ra
    if not job.get("unattended", True):
        return "needs the person in it"
    nb = job.get("not_before")
    if nb and nb > st.stamp():
        return "not before %s" % nb
    r = runner.pick_runner(cfg, job, budgets, state)
    if not r:
        asks = [b["runner"] for b in budgets.values() if b["mode"] == "ask"]
        return "no runner available: %s" % ("waiting for the person's answer on %s" % ", ".join(asks) if asks else "no runner command found")
    cd = (state.get("runner_cooldowns") or {}).get(r, "")
    if cd and cd > st.stamp():
        return "%s is resting after a failure until %s" % (r, cd)
    b = budgets[r]
    if b["mode"] == "ask":
        return "%s is at the person's reserve; waiting for their answer" % r
    if b["mode"] == "conservative":
        if not st.is_quiet(cfg):
            return "%s usage cannot be read, so it runs in quiet hours only" % r
        if state.get("daily", {}).get("%s:%s" % (r, st.now().date().isoformat()), 0) >= int(cfg["conservative"]["jobs_per_day"]):
            return "%s usage cannot be read and today's small cap is used" % r
    if st.is_heavy(cfg, job) and not st.heavy_ok(cfg):
        return "heavy job: waits for quiet hours or until the person is away"
    if st.files_clash(job, running, q):
        return "another job is running on the same project or files"
    for res in job.get("needs") or []:
        held = locks.holder(res)
        if held:
            return locks.wait_message(res, held)
    return ""


def ranked(q):
    def key(j):
        kind = j.get("source", "manual").split(":")[0]
        return (ORDER.get(kind, 2), j.get("not_before") or "", j.get("batch") or "zzz", j.get("estimate_tokens", 0), j["created"])
    return sorted([j for j in q["jobs"] if j["state"] == "todo"], key=key)


def choose(cfg, q, state, budgets):
    """The first job that may run now, and why every other queued job waits."""
    running = st.running_jobs(state, q)
    first, reasons = None, {}
    for j in ranked(q):
        why = why_not(cfg, q, state, j, budgets, running)
        if not why and first is None:
            first = j
        elif why:
            reasons[j["id"]] = why
    return first, reasons


def ask_to_continue(q, budgets):
    """File the ask-to-continue (once per window) for every runner at the reserve; returns the new ones."""
    new = []
    for b in budgets.values():
        if b["mode"] == "ask" and b.get("key"):
            before = len(q["questions"])
            x = usage.file_continue_question(q, b)
            if len(q["questions"]) > before:
                new.append(x)
    return new


# ---------------------------------------------------------------- commands

def cmd_init(args):
    path = st.home("config.json")
    if os.path.exists(path):
        out(args, {"config": path, "written": False}, "config already exists: %s" % path)
        return
    os.makedirs(st.home(), exist_ok=True)
    shutil.copyfile(TEMPLATE, path)
    out(args, {"config": path, "written": True}, "wrote a starter config: %s (edit the projects, then: scan)" % path)


def cmd_scan(args):
    cfg, q = st.load_config(), st.load_queue()
    report = sources.scan(cfg, q, only=args.project, run_tests=not args.no_tests)
    st.save_queue(q)
    out(args, report, "added %d jobs%s" % (len(report["added"]), ("; notes: " + "; ".join(report["notes"])) if report["notes"] else ""))


def cmd_add(args):
    cfg, q = st.load_config(), st.load_queue()
    p = st.project(cfg, args.project)
    job = st.new_job(p["id"], args.title, outcome=args.outcome, done=args.done or sources.done_checks(p), tier=args.tier,
                     estimate=args.estimate, unattended=not args.with_person, files=args.file, runner=args.runner,
                     stream=p["stream"], context=args.context or "", key="manual:" + args.title, needs=args.needs or None)
    sources.apply_needs(job, p)
    added = st.add_job(q, job)
    st.save_queue(q)
    out(args, {"job": job, "added": added}, "%s %s" % ("queued" if added else "already queued", job["id"]))


def cmd_list(args):
    q = st.load_queue()
    jobs = [j for j in q["jobs"] if args.all or j["state"] in ("todo", "doing", "question", "blocked")]
    rows = [{"id": j["id"], "state": j["state"], "project": j["project"], "tier": j["tier"], "title": j["title"],
             "source": j["source"], "runner": j.get("runner_used") or j["runner"], "note": j.get("note", "")} for j in jobs]
    print(json.dumps({"jobs": rows, "questions": [x for x in q["questions"] if not x.get("answer")]}, indent=2, ensure_ascii=False))


def cmd_next(args):
    cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
    budgets = budgets_for(cfg, q, allow_probe=False)
    job, reasons = choose(cfg, q, state, budgets)
    print(json.dumps({"next": job, "runner": runner.pick_runner(cfg, job, budgets, state) if job else "", "waiting": reasons,
                      "stopped": st.stopped()}, indent=2, ensure_ascii=False))


def cmd_run(args):
    cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
    budgets = budgets_for(cfg, q, allow_probe=not args.dry_run)
    if args.job:
        job = st.find_job(q, args.job)
        running = st.running_jobs(state, q)
        why = why_not(cfg, q, state, job, budgets, running)
        if why and not args.force:
            raise SystemExit("%s cannot run now: %s (add --force to run it anyway)" % (job["id"], why))
    else:
        job, reasons = choose(cfg, q, state, budgets)
        if not job:
            out(args, {"ran": None, "waiting": reasons}, "nothing can run now")
            return
    r = runner.pick_runner(cfg, job, budgets, state) or "claude"
    result = runner.run_job(cfg, q, state, job, r, dry_run=args.dry_run)
    if not args.dry_run:
        key = "%s:%s" % (r, st.now().date().isoformat())
        state.setdefault("daily", {})[key] = state.get("daily", {}).get(key, 0) + 1
        st.save_state(state)
    st.save_queue(q)
    out(args, result, "%s: %s (%s)" % (result["job"], result.get("state", "dry run"), result.get("note") or result.get("prompt", "")))


def digest_due(cfg, state):
    at = (cfg.get("digest") or {}).get("at") or "07:00"
    today = st.now().date().isoformat()
    return state.get("digest_sent", "") != today and st.now().hour * 60 + st.now().minute >= st.parse_hhmm(at)


def cmd_tick(args):
    why = st.stopped()
    if why:
        out(args, {"ran": [], "stopped": why}, "crew did not run: %s" % why)
        return
    if not st.take_tick_lock():
        out(args, {"ran": [], "stopped": "another tick is running"}, "another tick is running")
        return
    try:
        cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
        tests_key = "tests-scan"
        last = state.get(tests_key, "")
        run_tests = not last or (st.now() - datetime.datetime.fromisoformat(last)).total_seconds() > 60 * int(cfg.get("tests_every_minutes", 120))
        report = sources.scan(cfg, q, run_tests=run_tests)
        if run_tests:
            state[tests_key] = st.stamp()
        budgets = budgets_for(cfg, q, allow_probe=True)
        asked = ask_to_continue(q, budgets)
        ran = []
        for _ in range(max(1, int(args.max))):
            st.save_queue(q)
            job, reasons = choose(cfg, q, state, budgets)
            if not job:
                break
            r = runner.pick_runner(cfg, job, budgets, state) or "claude"
            ran.append(runner.run_job(cfg, q, state, job, r))
            key = "%s:%s" % (r, st.now().date().isoformat())
            state.setdefault("daily", {})[key] = state.get("daily", {}).get(key, 0) + 1
            budgets = budgets_for(cfg, q, allow_probe=False)
            asked += ask_to_continue(q, budgets)
        st.save_queue(q)
        sent = None
        if digest_due(cfg, state):
            sent = digest.make_digest(cfg, q)
            state["digest_sent"] = st.now().date().isoformat()
        if asked:
            digest.ping(asked[0]["question"][:190])
        st.save_state(state)
        st.save_queue(q)
        out(args, {"scanned": len(report["added"]), "ran": ran, "asked": [x["question"] for x in asked], "digest": sent,
                   "waiting": reasons if not ran else {}},
            "tick: %d added, %d ran%s" % (len(report["added"]), len(ran), ", digest sent" if sent else ""))
    finally:
        st.release_tick_lock()


def cmd_status(args):
    cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
    budgets = budgets_for(cfg, q, allow_probe=False)
    running = st.running_jobs(state, q)
    job, reasons = choose(cfg, q, state, budgets)
    counts = dict((s, sum(1 for j in q["jobs"] if j["state"] == s)) for s in st.STATES)
    open_q = [x for x in q["questions"] if not x.get("answer")]
    slim = dict((r, {"mode": b["mode"], "why": b["why"], "headroom": b["headroom"],
                     "windows": (b["reading"] or {}).get("windows", []), "read_at": (b["reading"] or {}).get("at", "")})
                for r, b in budgets.items())
    data = {"stopped": st.stopped(), "installed": inst.installed(), "quiet_now": st.is_quiet(cfg), "config": st.home("config.json"),
            "projects": [p["id"] for p in cfg["projects"]], "jobs": counts, "running": running, "next": job["id"] if job else "",
            "next_title": job["title"] if job else "", "waiting": reasons, "questions": open_q, "usage": slim,
            "digest_sent": state.get("digest_sent", ""), "last_digest": latest_digest()}
    data["next_step"] = next_step(data)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def latest_digest():
    folder = st.home("digests")
    if not os.path.isdir(folder):
        return ""
    files = sorted(f for f in os.listdir(folder) if f.endswith(".html"))
    return os.path.join(folder, files[-1]) if files else ""


def next_step(d):
    if d["stopped"]:
        return "crew is not running: %s" % d["stopped"]
    if d["questions"]:
        return "%d question(s) wait for the person: answer them (crew.py answer <id> \"...\") or let the defaults stand" % len(d["questions"])
    if not d["projects"]:
        return "no projects yet: edit %s, then crew.py scan" % d["config"]
    if not d["installed"]:
        return "the background job is not installed: crew.py install --dry-run, then install"
    if d["next"]:
        return "next job: %s (%s)" % (d["next"], d["next_title"])
    return "nothing can run now; the reasons are under waiting"


def cmd_branches(args):
    cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
    if args.project and args.project not in [p["id"] for p in cfg["projects"]]:
        msg = "No crew project %r. The projects are: %s" % (args.project, ", ".join(p["id"] for p in cfg["projects"]) or "none")
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
        raise SystemExit(msg)
    res = branches.report(cfg, q, state, project=args.project, prune=args.prune)
    out(args, res, branches.render_text(res))


def cmd_usage(args):
    cfg, q = st.load_config(), st.load_queue()
    print(json.dumps(budgets_for(cfg, q, allow_probe=args.probe), indent=2, ensure_ascii=False))


def cmd_digest(args):
    cfg, q, state = st.load_config(), st.load_queue(), st.load_state()
    r = digest.make_digest(cfg, q, send=not args.no_send)
    state["digest_sent"] = st.now().date().isoformat()
    st.save_state(state)
    out(args, r, "digest: %s (%s)" % (r["html"], r["line"]))


def cmd_answer(args):
    q = st.load_queue()
    hit = next((x for x in q["questions"] if x["key"] == args.id or x.get("job") == args.id), None)
    if not hit:
        raise SystemExit("No open question %r. crew.py list shows them." % args.id)
    hit["answer"], hit["answered"] = args.answer, st.stamp()
    if hit.get("job"):
        job = st.find_job(q, hit["job"])
        job["context"] = (job.get("context", "") + "\n\nThe person answered your question (%s): %s" % (job["question"], args.answer)).strip()
        job["state"], job["question"] = "todo", ""
    st.save_queue(q)
    out(args, {"answered": hit}, "answered %s" % args.id)


def cmd_retry(args):
    q = st.load_queue()
    job = st.find_job(q, args.job)
    if job["state"] not in ("blocked", "failed", "skipped"):
        raise SystemExit("%s is %s, not blocked or failed" % (job["id"], job["state"]))
    job.update(state="todo", note="", retry_after="", attempts=[], finished="")
    st.save_queue(q)
    out(args, {"job": job["id"], "state": "todo"}, "%s will run once more" % job["id"])


def cmd_drop(args):
    q = st.load_queue()
    job = st.find_job(q, args.job)
    q["jobs"] = [j for j in q["jobs"] if j["id"] != job["id"]]
    st.save_queue(q)
    out(args, {"dropped": job["id"]}, "dropped %s" % job["id"])


def cmd_pause(args):
    s = st.load_state()
    s["paused"] = args.command == "pause"
    st.save_state(s)
    out(args, {"paused": s["paused"]}, "crew is %s" % ("paused" if s["paused"] else "running again"))


def cmd_stopfile(args):
    if args.command == "stop":
        os.makedirs(st.home(), exist_ok=True)
        with open(st.stop_file(), "w", encoding="utf-8") as fh:
            fh.write("crew stopped by the person at %s\n" % st.stamp())
        out(args, {"stop_file": st.stop_file(), "stopped": True}, "stopped: nothing runs while %s exists" % st.stop_file())
    else:
        if os.path.exists(st.stop_file()):
            os.remove(st.stop_file())
        out(args, {"stop_file": st.stop_file(), "stopped": False}, "the stop file is gone; crew may run again")


def cmd_install(args):
    r = inst.install(args.every, args.dry_run)
    if args.json:
        print(json.dumps(r, indent=2))
        return
    print("%s on %s, every %d minutes. The tick honours: %s" % ("DRY RUN: would install" if r["dry_run"] else "Installed",
                                                                 r["platform"], r["every_minutes"], ", ".join(r["honours"])))
    print("home: %s, label: %s%s" % (r["home"], r["label"], (", file: " + r["path"]) if r.get("path") else ""))
    for w in r["writes"]:
        print("\n--- %s %s\n%s" % ("would write" if r["dry_run"] else "wrote", w["path"], w["content"].rstrip()))
    for cmd in r["runs"]:
        print("%s: %s" % ("would run" if r["dry_run"] else "ran", " ".join(cmd)))
    for n in r["notes"]:
        print("note: %s" % n)
    for name, text in (r.get("systemd") or {}).items():
        print("\n--- %s\n%s" % (name, text.rstrip()))


def cmd_uninstall(args):
    r = inst.uninstall(args.dry_run)
    out(args, r, "%s: %s (label %s)" % ("would remove" if args.dry_run else "removed", ", ".join(r["removes"]), r["label"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    sub.required = True

    def cmd(name, fn, **kw):
        s = sub.add_parser(name)
        s.add_argument("--json", action="store_true")
        s.set_defaults(fn=fn)
        return s
    cmd("init", cmd_init)
    s = cmd("scan", cmd_scan); s.add_argument("--project"); s.add_argument("--no-tests", action="store_true")
    s = cmd("add", cmd_add); s.add_argument("project"); s.add_argument("title"); s.add_argument("--outcome", default="")
    s.add_argument("--done", action="append"); s.add_argument("--tier", default="fast", choices=st.TIERS); s.add_argument("--estimate", type=int)
    s.add_argument("--file", action="append", default=[]); s.add_argument("--runner", default="auto"); s.add_argument("--context")
    s.add_argument("--with-person", action="store_true", help="the person must be in this job: listed, never run alone")
    s.add_argument("--needs", action="append", default=[], help="resources this job needs, for example chrome")
    s = cmd("list", cmd_list); s.add_argument("--all", action="store_true")
    cmd("next", cmd_next)
    s = cmd("run", cmd_run); s.add_argument("job", nargs="?"); s.add_argument("--dry-run", action="store_true"); s.add_argument("--force", action="store_true")
    s = cmd("tick", cmd_tick); s.add_argument("--max", type=int, default=1)
    cmd("status", cmd_status)
    s = cmd("branches", cmd_branches); s.add_argument("--project"); s.add_argument("--prune", action="store_true")
    s = cmd("usage", cmd_usage); s.add_argument("--probe", action="store_true")
    s = cmd("digest", cmd_digest); s.add_argument("--no-send", action="store_true")
    s = cmd("answer", cmd_answer); s.add_argument("id"); s.add_argument("answer")
    s = cmd("retry", cmd_retry); s.add_argument("job")
    s = cmd("drop", cmd_drop); s.add_argument("job")
    cmd("pause", cmd_pause); cmd("resume", cmd_pause)
    cmd("stop", cmd_stopfile); cmd("go", cmd_stopfile)
    s = cmd("install", cmd_install); s.add_argument("--every", type=int, default=15); s.add_argument("--dry-run", action="store_true")
    s = cmd("uninstall", cmd_uninstall); s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
