#!/usr/bin/env python3
"""mStack's shared tool: which skills are on, the private journal, "review my skills", and "ping me".

Python 3.9 or later, standard library only. Everything stays on this computer in ~/.mstack (or
$MSTACK_HOME) unless the person turns on a phone service such as ntfy themselves.

  skills [--json]                      every mStack skill, and whether it is on
  enabled <skill>                      exit 0 if the skill is on, 1 if the person switched it off (a name that is not a skill: exit 2)
  disable <skill> | enable <skill>     switch a skill off or on everywhere (~/.mstack/config.json)
  session-start                        the always-on rules for this session (used by the Claude Code plugin hook)
  routing                              the same rules as a block for AGENTS.md or Cursor rules

  log <skill> --outcome reached|partial|not-reached [--needed-user ...] [--stalled ...] [--correction ...] [--note ...]
                                       record privately how one use of a skill went
  review [--skill X] [--json]          read the journal as evidence for proposed improvements (changes nothing)
  review --done                        mark the journal reviewed and write the day's evidence file
  learn <skill> "<rule>"               keep an improvement the person accepted (~/.mstack/learned/<skill>.md)
  learned [<skill>]                    print the accepted improvements, numbered (every skill that has some, with no name)
  unlearn <skill> <n>                  remove rule number n, as numbered by learned

  ping "<message>" [--title T]         notify the person now (desktop, plus their own phone service if set up)
  ping hook                            for Claude Code's Notification and Stop hooks (reads the event on stdin)
  ping codex-event '<json>'            for Codex's notify setting
  ping test                            send a test notification
  setup claude-hooks|codex|cursor      show what would be written; add --write after the person says yes; --remove undoes it
  setup ntfy [--topic T] [--server S]  guided opt-in to a free phone push service; --write after the person says yes

Every command takes --json: one JSON object, and an error is {"ok": false, "error": "..."} with a non-zero exit.
Reply text stays out of hook notifications unless config.json has "notify_reply_text": true.
"""
import argparse
import contextlib
import io
import json
import os
import shlex
import sys

from mbase import (HERE, SKILLS, Fail, JsonArgParser, check_skill, home, is_on, load_config,  # noqa: F401
                   report_failure, save_config, say, skills)
sys.path.insert(0, HERE)
import rules as rules_file  # noqa: E402  (the rules file per project)
import brief as brief_tool  # noqa: E402  (one line becomes a complete brief)
import journal_review as journal_cmds  # noqa: E402
import learned as learned_cmds  # noqa: E402
import notify as notify_cmds  # noqa: E402
import setup_agents  # noqa: E402
import setup_codex  # noqa: E402
import setup_ntfy  # noqa: E402
from journal_review import OUTCOMES, journal, last_review  # noqa: E402,F401

SELF = os.path.abspath(__file__)


def cmd_skills(args):
    cfg = load_config()
    rows = [dict(name=s["name"], on=is_on(s["name"], cfg), summary=s["summary"], folder=s["folder"]) for s in skills()]
    say(args, {"ok": True, "skills": rows, "config": home("config.json")},
        "\n".join("%-16s %-4s %s" % (r["name"], "on" if r["on"] else "off", r["summary"]) for r in rows))


def cmd_enabled(args):
    on = is_on(check_skill(args.skill))
    say(args, {"ok": True, "skill": args.skill, "on": on},
        "on" if on else "off: switched off in %s" % home("config.json"))
    sys.exit(0 if on else 1)


def cmd_switch(args):
    cfg = load_config()
    check_skill(args.skill)
    off = [x for x in cfg.get("disabled", []) if x != args.skill]
    if args.command == "disable":
        off.append(args.skill)
    cfg["disabled"] = off
    save_config(cfg)
    say(args, {"ok": True, "skill": args.skill, "on": args.command == "enable", "config": home("config.json")},
        "%s is now %s (%s)" % (args.skill, "off" if args.command == "disable" else "on", home("config.json")))


# ---------------------------------------------------------------- the always-on rules

def rules(for_hook):
    cfg = load_config()
    all_ = skills()
    on = [s for s in all_ if is_on(s["name"], cfg) and s["name"] != "mstack"]
    off = [s["name"] for s in all_ if not is_on(s["name"], cfg)]
    tool = "python3 %s" % shlex.quote(SELF)
    lines = ["mStack is installed. Its skills switch on by themselves when relevant: the person never has to name "
             "one. Follow a skill's SKILL.md when its moment comes:"]
    for s in on:
        lines.append("- %s: %s (%s)" % (s["name"], s["summary"], os.path.join(s["folder"], "SKILL.md")))
    if off:
        lines.append("Switched off by the person (do not use): %s. If they say \"don't use <skill>\" for a task, "
                     "honour it for that task." % ", ".join(off))
    lines.append("To switch a skill off for good, run only: %s disable <skill> (it writes %s). Never edit CLAUDE.md, "
                 "AGENTS.md, settings.json or any other instructions or settings file for a switch, and never unset "
                 "MSTACK_HOME to reach another home." % (tool, home("config.json")))
    names = [s["name"] for s in on]
    if "ping-me" in names:
        lines.append("Always on, ping me: whenever you need the person's decision or input, or a task they asked for "
                     "is complete or blocked, notify them at once without being asked (%s; one line under 200 "
                     "characters, leading with what they would act on). Batch questions into one ping. %s" % (
                         "the PushNotification tool" if for_hook else "your agent's own notification, or: %s ping \"<message>\"" % tool,
                         "It reaches their phone only while Remote Control is connected; if the tool says it was not sent, "
                         "say so in your reply rather than claiming they were pinged." if for_hook else
                         "That is a desktop alert; it reaches a phone only if the person has set up ntfy (%s setup ntfy)." % tool))
    if "outcome-first" in names:
        lines.append("Always on, outcome first: for any task bigger than a few steps, pin down the outcome and what "
                     "done looks like, ask every question in one batch with defaults, then run to a verified outcome "
                     "without further input (see outcome-first's SKILL.md).")
    if "away-mode" in names:
        away = os.path.join(SKILLS, "away-mode", "scripts", "away.py")
        lines.append("Always on, away mode: before presenting any file, report, mockup, screenshot or link, run "
                     "python3 %s status (add --hint \"<what the harness told you>\" if it said the person follows from "
                     "another device, or a push was not sent because they are at the terminal). If away is true or "
                     "unsure, make phone-readable copies (python3 %s render <file-or-address>), send them to the chat "
                     "(%s), put the 3 to 5 key points in the reply, and never end with only a local path or an open "
                     "command. When they say they are on their phone or back, record it: python3 %s set away|back." % (
                         shlex.quote(away), shlex.quote(away),
                         "the SendUserFile tool" if for_hook else "your agent's file-sending tool, or a private link",
                         shlex.quote(away)))
    if "crew" in names and os.path.exists(home("crew", "config.json")):
        crew = os.path.join(SKILLS, "crew", "scripts", "crew.py")
        lines.append("Always on, crew: the person's crew is set up. At a natural pause, or when they ask what finished, run "
                     "python3 %s status and tell them what finished, what waits for them (answer with python3 %s answer "
                     "<id> \"...\"), and the usage against the cap. When they ask what is happening across their projects, run "
                     "python3 %s status instead. Never install, push or answer a question for them." % (
                         shlex.quote(crew), shlex.quote(crew), shlex.quote(os.path.join(HERE, "status.py"))))
    here = rules_file.find_project(os.getcwd()) if for_hook else None
    if here and os.path.exists(os.path.join(here, "rules.md")):
        lines.append("This project's rules: %s. Every brief you write for another agent must carry them: python3 %s show "
                     "--project %s --brief. Starting another agent? Write its brief with python3 %s <kind> \"<goal>\" "
                     "--project %s." % (os.path.join(here, "rules.md"), shlex.quote(os.path.join(HERE, "rules.py")),
                                       shlex.quote(os.getcwd()), shlex.quote(os.path.join(HERE, "brief.py")),
                                       shlex.quote(os.getcwd())))
    lines.append("After an mStack skill is used, record privately how it went: %s log <skill> --outcome "
                 "reached|partial|not-reached [--needed-user ...] [--stalled ...] [--correction ...]. If "
                 "%s exists, it holds the person's accepted improvements to that skill: follow it." % (
                     tool, home("learned", "<skill>.md")))
    due = []
    for s in on:
        n = len(journal(s["name"]))
        seen = (last_review(s["name"]) or {}).get("uses", 0)
        if n - seen >= int(cfg.get("review_every", 10)):
            due.append("%s (%d uses since its last review)" % (s["name"], n - seen))
    if due:
        lines.append("Review due: %s. At a natural pause, offer once to \"review my skills\" (the mstack skill)." %
                     "; ".join(due))
    return "\n".join(lines)


def cmd_session_start(args):
    say(args, {"ok": True, "text": rules(for_hook=True)}, rules(for_hook=True))


def cmd_routing(args):
    block = "<!-- mstack:start -->\n## mStack\n\n%s\n<!-- mstack:end -->" % rules(for_hook=False)
    say(args, {"ok": True, "text": block}, block)


def cmd_setup(args):
    routing = rules(for_hook=False)
    if args.target == "claude-hooks":
        out = setup_agents.setup_claude(args)
    elif args.target == "codex":
        out = setup_codex.setup_codex(args, routing)
    elif args.target == "cursor":
        out = setup_agents.setup_cursor(args, routing)
    else:
        out = setup_ntfy.setup_ntfy(args)
    say(args, out, out["message"])


def delegate(fn, argv, prog):
    """Run rules, status or brief. With --json their errors come out as JSON too."""
    call = (lambda: fn(argv, prog)) if prog else (lambda: fn(argv))
    if "--json" not in argv:
        return call()
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            result = call()
    except SystemExit as e:
        if e.code in (None, 0):
            sys.stderr.write(err.getvalue())
            raise
        lines = [x for x in err.getvalue().strip().splitlines() if x.strip()]
        message = lines[-1] if lines else (e.code if isinstance(e.code, str) else "failed")
        print(json.dumps({"ok": False, "error": message}, indent=2))
        raise SystemExit(e.code if isinstance(e.code, int) else 1)
    sys.stderr.write(err.getvalue())
    return result


def build_parser():
    ap = JsonArgParser(prog="mstack.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn, *positional, **kw):
        s = sub.add_parser(name, **kw)
        for p in positional:
            s.add_argument(p)
        if name not in ("status", "rules", "brief"):
            s.add_argument("--json", action="store_true", help="print one JSON object")
        s.set_defaults(fn=fn)
        return s

    add("skills", cmd_skills)
    add("enabled", cmd_enabled, "skill")
    add("disable", cmd_switch, "skill")
    add("enable", cmd_switch, "skill")
    add("session-start", cmd_session_start)
    add("routing", cmd_routing)
    s = add("log", journal_cmds.cmd_log, "skill")
    s.add_argument("--outcome", required=True, choices=OUTCOMES)
    s.add_argument("--needed-user", action="append", default=[], help="where it needed the person (repeatable)")
    s.add_argument("--stalled", action="append", default=[], help="where it stalled (repeatable)")
    s.add_argument("--correction", action="append", default=[], help="a correction the person made (repeatable)")
    s.add_argument("--note", default="")
    s = add("review", journal_cmds.cmd_review)
    s.add_argument("--skill")
    s.add_argument("--done", action="store_true", help="mark the journal as reviewed and write the day's evidence file")
    s.add_argument("--dry-run", action="store_true", help="a plain read (the default): write nothing")
    add("learn", learned_cmds.cmd_learn, "skill", "rule")
    s = add("learned", learned_cmds.cmd_learned)
    s.add_argument("skill", nargs="?", help="one skill (default: every skill that has learned rules)")
    s = add("unlearn", learned_cmds.cmd_unlearn, "skill")
    s.add_argument("number", type=int, help="the rule number shown by learned")
    s = add("ping", notify_cmds.cmd_ping, "message", help="notify the person now")
    s.add_argument("extra", nargs="?", default="", help="the JSON Codex passes to its notify program")
    s.add_argument("--title", default="mStack")
    s.add_argument("--also", help="codex-event: the person's previous notify program, as a JSON list, to run as well")
    for name, text in (("status", "every project at once, what waits for you first (see status.py)"),
                       ("rules", "a rules file per project: init, show, list, import, accept (see rules.py)"),
                       ("brief", "one line becomes a complete brief for another agent (see brief.py)")):
        sub.add_parser(name, help=text)
    s = add("setup", cmd_setup)
    s.add_argument("target", choices=("claude-hooks", "codex", "cursor", "ntfy"))
    s.add_argument("--write", action="store_true", help="make the change (only after the person says yes)")
    s.add_argument("--remove", action="store_true", help="take mStack's change out again")
    s.add_argument("--topic", help="ntfy: the private topic name (default: a long random one)")
    s.add_argument("--server", help="ntfy: the server (default https://ntfy.sh; https unless it is on this computer)")
    s.add_argument("--settings", help="claude-hooks: the settings file (default ~/.claude/settings.json)")
    s.add_argument("--codex-config", help="codex: the config file (default ~/.codex/config.toml)")
    s.add_argument("--project", help="cursor: the project folder (default: here)")
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    JsonArgParser.json_mode = "--json" in argv
    also = None
    if argv[:1] == ["ping"] and "--also" in argv:            # Codex puts the event last, after --also <program>
        i = argv.index("--also")
        also = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    if argv[:1] == ["rules"]:                                # a rules file per project: see rules.py
        return delegate(rules_file.main, argv[1:], "mstack.py rules")
    if argv[:1] == ["status"]:                               # status across everything: see status.py
        import status as status_view
        return delegate(status_view.main, argv[1:], None)
    if argv[:1] == ["brief"]:                                # one line becomes a brief: see brief.py
        return delegate(brief_tool.main, argv[1:], "mstack.py brief")
    args = build_parser().parse_args(argv)
    if also is not None:
        args.also = also
    try:
        args.fn(args)
    except Fail as e:
        report_failure(e, getattr(args, "json", False))


if __name__ == "__main__":
    main()
