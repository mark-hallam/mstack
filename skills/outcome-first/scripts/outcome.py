#!/usr/bin/env python3
"""Outcome first: a durable plan and progress file that carries a task to a verified outcome.

Python 3.9 or later, standard library only. Each outcome lives in ~/.mstack/outcomes/<slug>/ (or
$MSTACK_HOME/outcomes): outcome.json for agents, progress.md for people and for any agent picking the
work up after a restart. Every command takes --json.

  new "<outcome>" --done "<what done looks like>[::<command that proves it>]" ...   start one
  list                                     every outcome and its state
  status [<slug>]                          where it stands and the next step (the latest outcome by default)
  task add <slug> "<title>" [--after t1,t2] [--who subagent|session|agent|person]
  task set <slug> <id> --state todo|doing|done|blocked [--evidence ...] [--note ...]
  ready <slug>                             the tasks that can run now, in parallel
  ask <slug> "<question>" [--default ...] [--why ...]   queue a decision that is genuinely the person's
  questions <slug>                         the open questions, to ask in one batch
  answer <slug> <q-id> "<answer>"          or: answer <slug> --defaults (nobody can answer) or "defaults" (the person said so)
  note <slug> "<progress note>"
  check <slug>                             run every done check; achieved only when all pass with evidence
  verify <slug> <d-id> --evidence "..."    record evidence for a done check that has no command
  schedule <slug> (--in-minutes N | --at "YYYY-MM-DD HH:MM") [--dry-run]   resume later (usage limits)
  unschedule <slug>
  resume <slug>                            run the saved resume command (what the schedule calls)
"""
import argparse
import budget
from jsoncli import JsonParser, run_cli
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SELF = os.path.abspath(__file__)
STATES = ("todo", "doing", "done", "blocked")


def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, "outcomes", *parts)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:6]) or "outcome"


def load(slug):
    path = home(slug, "outcome.json")
    if not os.path.exists(path):
        raise SystemExit("No outcome %r. Run: list" % slug)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def latest():
    if not os.path.isdir(home()):
        return None
    found = [d for d in os.listdir(home()) if os.path.exists(home(d, "outcome.json"))]
    return max(found, key=lambda d: os.path.getmtime(home(d, "outcome.json"))) if found else None


def save(o):
    o["updated"] = now()
    os.makedirs(home(o["slug"]), exist_ok=True)
    tmp = home(o["slug"], "outcome.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(o, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, home(o["slug"], "outcome.json"))           # never half written, even on a crash
    with open(home(o["slug"], "progress.md"), "w", encoding="utf-8") as fh:
        fh.write(progress_md(o))


def ready_tasks(o):
    done = set(t["id"] for t in o["tasks"] if t["state"] == "done")
    return [t for t in o["tasks"] if t["state"] == "todo" and all(a in done for a in t["after"])]


def open_questions(o):
    return [q for q in o["questions"] if q.get("answer") is None]


def state_of(o):
    if o.get("achieved"):
        return "achieved"
    if open_questions(o) and not ready_tasks(o) and not any(t["state"] == "doing" for t in o["tasks"]):
        return "waiting for the person"
    if any(t["state"] == "blocked" for t in o["tasks"]) and not ready_tasks(o):
        return "blocked"
    return "in progress"


def next_step(o):
    st = state_of(o)
    if st == "achieved":
        return "Report once to the person: the outcome, the evidence for each done check, and anything left for them."
    qs = open_questions(o)
    ready = ready_tasks(o)
    doing = [t for t in o["tasks"] if t["state"] == "doing"]
    if not o["tasks"]:
        return "Plan: add the tasks (task add), marking what can run in parallel with --after."
    if ready:
        return "Start these in parallel, each with its own subagent or session: %s" % ", ".join(
            "%s (%s)" % (t["id"], t["title"]) for t in ready)
    if doing:
        return "Wait for %s, then mark each done with its evidence." % ", ".join(t["id"] for t in doing)
    if qs:
        return "Ask the person these in one batch, with the defaults: %s" % ", ".join(q["id"] for q in qs)
    if any(t["state"] == "blocked" for t in o["tasks"]):
        return "Unblock: %s. If only the person can, add it to the questions and ask in one batch." % ", ".join(
            t["id"] for t in o["tasks"] if t["state"] == "blocked")
    return "Every task is done: run check to verify the outcome with evidence."


def progress_md(o):
    lines = ["# Outcome: %s" % o["outcome"], "",
             "State: **%s**. Updated %s. Read this file first when picking the work up again." % (state_of(o), o["updated"]),
             "", "Next: %s" % next_step(o), "", "## Done looks like", ""]
    for d in o["done"]:
        mark = {"pass": "[x]", "fail": "[ ]", None: "[ ]"}.get(d.get("result"))
        how = " (proved by: `%s`)" % d["command"] if d.get("command") else ""
        ev = "\n  Evidence: %s" % d["evidence"] if d.get("evidence") else ""
        lines.append("- %s %s: %s%s%s" % (mark, d["id"], d["text"], how, ev))
    lines += ["", "## Tasks", ""]
    for t in o["tasks"]:
        after = " (after %s)" % ", ".join(t["after"]) if t["after"] else ""
        ev = "; evidence: %s" % t["evidence"] if t.get("evidence") else ""
        lines.append("- %s [%s] %s%s, by %s%s" % (t["id"], t["state"], t["title"], after, t["who"], ev))
    if not o["tasks"]:
        lines.append("- (none yet)")
    if o["questions"]:
        lines += ["", "## Questions for the person", ""]
        for q in o["questions"]:
            lines.append("- %s: %s%s%s" % (q["id"], q["text"], " Default: %s." % q["default"] if q.get("default") else "",
                " Answer: %s%s" % (q["answer"], " (taken by default)" if q.get("by_default") else "") if q.get("answer") is not None else " (open)"))
    if o.get("schedule"):
        lines += ["", "Resume scheduled for %s." % o["schedule"]["at"]]
    lines += ["", "## Log", ""] + ["- %s %s" % (n["at"], n["text"]) for n in o["log"][-30:]]
    return "\n".join(lines) + "\n"


def out(args, data, text):
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def summary(o):
    return {"slug": o["slug"], "outcome": o["outcome"], "state": state_of(o), "next": next_step(o),
            "ready": [t["id"] for t in ready_tasks(o)], "open_questions": [q["id"] for q in open_questions(o)],
            "done_checks": [dict(id=d["id"], text=d["text"], result=d.get("result")) for d in o["done"]],
            "progress_file": home(o["slug"], "progress.md")}


# ---------------------------------------------------------------- commands

def cmd_new(args):
    slug = args.slug or slugify(args.outcome)
    if os.path.exists(home(slug, "outcome.json")) and not args.force:
        raise SystemExit("An outcome called %s already exists (use --slug or --force)" % slug)
    done = []
    for i, d in enumerate(args.done, 1):
        text, _, command = d.partition("::")
        done.append({"id": "d%d" % i, "text": text.strip(), "command": command.strip() or None, "result": None})
    if not done:
        raise SystemExit("Say what done looks like with at least one --done (add ::<command> where a command can prove it).")
    o = {"slug": slug, "outcome": args.outcome, "created": now(), "updated": now(), "cwd": os.path.abspath(args.cwd),
         "done": done, "tasks": [], "questions": [], "log": [{"at": now(), "text": "Outcome set."}],
         "resume_command": args.resume_command, "achieved": False, "schedule": None}
    save(o)
    out(args, summary(o), "started %s\nprogress file: %s" % (slug, home(slug, "progress.md")))


def cmd_list(args):
    rows = []
    if os.path.isdir(home()):
        for d in sorted(os.listdir(home())):
            if os.path.exists(home(d, "outcome.json")):
                o = load(d)
                rows.append({"slug": d, "state": state_of(o), "outcome": o["outcome"]})
    out(args, {"outcomes": rows}, "\n".join("%-32s %-24s %s" % (r["slug"], r["state"], r["outcome"]) for r in rows)
        or "No outcomes yet.")


def pick(args):
    slug = getattr(args, "slug", None) or latest()
    if not slug:
        raise SystemExit("No outcomes yet. Run: new")
    return load(slug)


def cmd_status(args):
    o = pick(args)
    out(args, summary(o), progress_md(o))


def cmd_task(args):
    o = load(args.slug)
    if args.action == "add":
        tid = "t%d" % (len(o["tasks"]) + 1)
        after = [a for a in (args.after or "").split(",") if a]
        known = set(t["id"] for t in o["tasks"])
        if any(a not in known for a in after):
            raise SystemExit("--after names a task that does not exist: %s" % ", ".join(a for a in after if a not in known))
        o["tasks"].append({"id": tid, "title": args.title, "after": after, "who": args.who, "state": "todo",
                           "evidence": None})
        o["log"].append({"at": now(), "text": "Planned %s: %s" % (tid, args.title)})
        save(o)
        out(args, {"id": tid, "ready": [t["id"] for t in ready_tasks(o)]}, "added %s" % tid)
        return
    if not args.state:
        raise SystemExit("task set needs --state")
    t = next((t for t in o["tasks"] if t["id"] == args.title), None)
    if not t:
        raise SystemExit("No task %r" % args.title)
    if args.state == "done" and not args.evidence:
        raise SystemExit("A task is done only with evidence: add --evidence (a test result, a file, an address, a screenshot).")
    t["state"] = args.state
    if args.evidence:
        t["evidence"] = args.evidence
    o["log"].append({"at": now(), "text": "%s is %s%s" % (t["id"], args.state, ": " + args.note if args.note else "")})
    save(o)
    out(args, summary(o), "%s is %s. Next: %s" % (t["id"], args.state, next_step(o)))


def cmd_ready(args):
    o = load(args.slug)
    r = ready_tasks(o)
    out(args, {"ready": r}, "\n".join("%s  %s (%s)" % (t["id"], t["title"], t["who"]) for t in r) or "Nothing ready.")


def cmd_ask(args):
    o = load(args.slug)
    qid = "q%d" % (len(o["questions"]) + 1)
    o["questions"].append({"id": qid, "text": args.question, "default": args.default, "why": args.why, "answer": None})
    save(o)
    out(args, {"id": qid, "open": [q["id"] for q in open_questions(o)]}, "queued %s (%d open)" % (qid, len(open_questions(o))))


def cmd_questions(args):
    o = load(args.slug)
    qs = open_questions(o)
    cap = budget.cap_from(os.path.join(os.path.dirname(home()), "config.json"))
    ask, rest = budget.split(qs, cap)
    text = budget.render(ask, rest, cap)
    out(args, {"ask": ask, "by_default": rest, "cap": cap, "questions": qs}, text)


def cmd_answer(args):
    o = load(args.slug)
    word = (args.qid or "").lower() in ("defaults", "go", "all defaults", "use the defaults") and args.answer is None
    if args.defaults or word:
        taken = []
        for q in open_questions(o):
            if q.get("default"):
                q["answer"] = q["default"] if word else "%s (the default; nobody could answer, so it was taken and noted)" % q["default"]
                q["by_default"] = word
                taken.append(q["id"])
        who = ", ".join(taken) or "none had a default"
        o["log"].append({"at": now(), "text": "The person chose the defaults for %s." % who if word else
                         "Nobody could answer %s: the defaults were taken (%s)." % (", ".join(taken) or "the questions", who)})
        save(o)
        left = [q["id"] for q in open_questions(o)]
        out(args, dict(summary(o), taken=taken, still_open=left),
            "took the defaults for %s%s" % (", ".join(taken) or "nothing", "; still open (no default): %s" % ", ".join(left) if left else ""))
        return
    if not args.qid or args.answer is None:
        raise SystemExit("answer needs a question id and an answer, or --defaults.")
    q = next((q for q in o["questions"] if q["id"] == args.qid), None)
    if not q:
        raise SystemExit("No question %r" % args.qid)
    q["answer"] = args.answer
    q["by_default"] = False
    o["log"].append({"at": now(), "text": "%s answered: %s" % (q["id"], args.answer)})
    save(o)
    out(args, summary(o), "recorded. Next: %s" % next_step(o))


def cmd_note(args):
    o = load(args.slug)
    o["log"].append({"at": now(), "text": args.text})
    save(o)
    out(args, {"ok": True}, "noted")


def cmd_check(args):
    o = load(args.slug)
    for d in o["done"]:
        if d.get("command"):
            try:
                r = subprocess.run(d["command"], shell=True, cwd=o["cwd"], capture_output=True, text=True,
                                   timeout=args.timeout)
                tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
                d["result"] = "pass" if r.returncode == 0 else "fail"
                d["evidence"] = "`%s` exited %d at %s%s" % (d["command"], r.returncode, now(),
                                                            (": " + " / ".join(tail))[:300] if tail else "")
            except subprocess.TimeoutExpired:
                d["result"], d["evidence"] = "fail", "`%s` timed out after %ss" % (d["command"], args.timeout)
    tasks_done = all(t["state"] == "done" for t in o["tasks"])
    checks_pass = all(d.get("result") == "pass" and d.get("evidence") for d in o["done"])
    open_qs = [q["id"] for q in open_questions(o)]
    o["achieved"] = bool(tasks_done and checks_pass and not open_qs)
    o["log"].append({"at": now(), "text": "Checked: %s" % ("achieved" if o["achieved"] else "not yet")})
    save(o)                                                   # the progress file is always current after a check
    data = summary(o)
    data["achieved"] = o["achieved"]
    data["unfinished_tasks"] = [t["id"] for t in o["tasks"] if t["state"] != "done"]
    data["open_tasks"] = [{"id": t["id"], "title": t["title"], "state": t["state"], "who": t["who"]}
                          for t in o["tasks"] if t["state"] != "done"]
    left = "".join("\n  %s  %s (%s, %s)" % (t["id"], t["title"], t["state"], t["who"]) for t in data["open_tasks"])
    if left:
        data["to_mark_done"] = "task set %s <id> --state done --evidence \"...\"" % o["slug"]
        left = "\nOpen tasks:%s\nMark one done with: %s" % (left, data["to_mark_done"])
    why = ""
    if open_qs and tasks_done and checks_pass:
        why = " A question for the person is still open (%s): answer it, or take the defaults (answer --defaults)." % ", ".join(open_qs)
    out(args, data, "%s\n%s\nprogress file: %s" % (
        "ACHIEVED: every done check passed with evidence and no question is open." if o["achieved"] else "Not yet." + why + left,
        "\n".join("%s %s: %s" % (d["id"], d.get("result") or "no evidence yet", d["text"]) for d in o["done"]),
        home(o["slug"], "progress.md")))
    sys.exit(0 if o["achieved"] else 1)


def cmd_verify(args):
    o = load(args.slug)
    d = next((d for d in o["done"] if d["id"] == args.did), None)
    if not d:
        raise SystemExit("No done check %r" % args.did)
    if d.get("command"):
        raise SystemExit("%s is proved by a command: run check." % args.did)
    d["result"], d["evidence"] = "pass", args.evidence
    o["log"].append({"at": now(), "text": "%s verified: %s" % (args.did, args.evidence)})
    save(o)
    out(args, summary(o), "recorded evidence for %s" % args.did)


# ---------------------------------------------------------------- resuming after a usage limit

def crontab_cmd():
    return shlex.split(os.environ.get("MSTACK_CRONTAB") or "crontab")


def read_crontab():
    r = subprocess.run(crontab_cmd() + ["-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def write_crontab(text):
    subprocess.run(crontab_cmd() + ["-"], input=text, text=True, check=True)


def marker(slug):
    return "# mstack-resume:%s" % slug


def resolve_program(command):
    """The full path of the program a resume command starts with. Refuses one that cannot be found now,
    because cron (with its bare PATH) could not find it later either."""
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        raise SystemExit("The resume command is empty or cannot be parsed: %r" % command)
    found = shutil.which(first)
    if not found:
        raise SystemExit("The resume command starts with %r, which is not on this PATH, so a scheduled resume would fail. "
                         "Use its full path (for example the output of: which codex) or a command that exists, and try "
                         "it once by hand first." % first)
    return found


def cmd_schedule(args):
    o = load(args.slug)
    if not o.get("resume_command"):
        raise SystemExit("This outcome has no resume command. Set one with: new ... --resume-command \"...\" --force, "
                         "or use your agent's own scheduler.")
    when = (datetime.datetime.now() + datetime.timedelta(minutes=args.in_minutes)) if args.in_minutes is not None else \
        datetime.datetime.strptime(args.at, "%Y-%m-%d %H:%M")
    program = resolve_program(o["resume_command"])
    py = sys.executable or "python3"
    # cron runs with a bare PATH where claude, codex and node are not found, so the line carries this PATH,
    # exported (an assignment in front of cd would only last for the cd).
    env = "export PATH=%s; " % shlex.quote(os.environ.get("PATH", ""))
    if os.environ.get("MSTACK_HOME"):
        env += "export MSTACK_HOME=%s; " % shlex.quote(os.environ["MSTACK_HOME"])
    line = "%d %d %d %d * %scd %s && %s %s resume %s >> %s 2>&1 %s" % (
        when.minute, when.hour, when.day, when.month, env, shlex.quote(o["cwd"]), shlex.quote(py), shlex.quote(SELF),
        shlex.quote(o["slug"]), shlex.quote(home(o["slug"], "resume.log")), marker(o["slug"]))
    if args.dry_run:
        out(args, {"line": line, "at": when.isoformat(timespec="minutes"), "program": program}, line)
        return
    current = [l for l in read_crontab().splitlines() if marker(o["slug"]) not in l]
    write_crontab("\n".join(current + [line]) + "\n")
    o["schedule"] = {"at": when.isoformat(timespec="minutes"), "how": "crontab", "program": program}
    o["log"].append({"at": now(), "text": "Resume scheduled for %s." % o["schedule"]["at"]})
    save(o)
    out(args, {"scheduled": o["schedule"], "line": line}, "resume scheduled for %s" % o["schedule"]["at"])


def unschedule(slug):
    text = read_crontab()
    keep = [l for l in text.splitlines() if marker(slug) not in l]
    if len(keep) != len(text.splitlines()):
        write_crontab("\n".join(keep) + ("\n" if keep else ""))
        return True
    return False


def cmd_unschedule(args):
    o = load(args.slug)
    removed = unschedule(o["slug"])
    o["schedule"] = None
    save(o)
    out(args, {"removed": removed}, "removed" if removed else "nothing was scheduled")


def cmd_resume(args):
    o = load(args.slug)
    unschedule(o["slug"])                                     # a one-off: it never runs twice
    o["schedule"] = None
    o["log"].append({"at": now(), "text": "Resumed."})
    save(o)
    if o.get("achieved"):
        out(args, {"ok": True, "achieved": True, "resumed": False}, "Already achieved; nothing to resume.")
        return
    r = subprocess.run(o["resume_command"], shell=True, cwd=o["cwd"])
    sys.exit(r.returncode)


def main(argv=None):
    ap = JsonParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn):
        s = sub.add_parser(name)
        s.add_argument("--json", action="store_true")
        s.set_defaults(fn=fn)
        return s

    s = add("new", cmd_new)
    s.add_argument("outcome")
    s.add_argument("--done", action="append", default=[], help="what done looks like[::a command that proves it]")
    s.add_argument("--slug")
    s.add_argument("--cwd", default=".")
    s.add_argument("--resume-command", help="the command that resumes the work in a new agent session")
    s.add_argument("--force", action="store_true")
    add("list", cmd_list)
    s = add("status", cmd_status)
    s.add_argument("slug", nargs="?")
    s = add("task", cmd_task)
    s.add_argument("action", choices=("add", "set"))
    s.add_argument("slug")
    s.add_argument("title", help="add: the task's title; set: its id")
    s.add_argument("--after")
    s.add_argument("--who", default="agent", choices=("agent", "subagent", "session", "person"))
    s.add_argument("--state", choices=STATES)
    s.add_argument("--evidence")
    s.add_argument("--note")
    s = add("ready", cmd_ready)
    s.add_argument("slug")
    s = add("ask", cmd_ask)
    s.add_argument("slug")
    s.add_argument("question")
    s.add_argument("--default")
    s.add_argument("--why")
    s = add("questions", cmd_questions)
    s.add_argument("slug")
    s = add("answer", cmd_answer)
    s.add_argument("slug")
    s.add_argument("qid", nargs="?")
    s.add_argument("answer", nargs="?")
    s.add_argument("--defaults", action="store_true", help="nobody can answer: take every default and note it")
    s = add("note", cmd_note)
    s.add_argument("slug")
    s.add_argument("text")
    s = add("check", cmd_check)
    s.add_argument("slug")
    s.add_argument("--timeout", type=int, default=900)
    s = add("verify", cmd_verify)
    s.add_argument("slug")
    s.add_argument("did")
    s.add_argument("--evidence", required=True)
    s = add("schedule", cmd_schedule)
    s.add_argument("slug")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--in-minutes", type=int)
    g.add_argument("--at")
    s.add_argument("--dry-run", action="store_true")
    s = add("unschedule", cmd_unschedule)
    s.add_argument("slug")
    s = add("resume", cmd_resume)
    s.add_argument("slug")
    run_cli(ap, argv)


if __name__ == "__main__":
    main()
