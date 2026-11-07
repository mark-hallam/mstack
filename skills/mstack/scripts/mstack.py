#!/usr/bin/env python3
"""mStack's shared tool: which skills are on, the private journal, "review my skills", and "ping me".

Python 3.9 or later, standard library only. Everything stays on this computer in ~/.mstack (or
$MSTACK_HOME) unless the person turns on a phone service such as ntfy themselves.

  skills [--json]                      every mStack skill, and whether it is on
  enabled <skill>                      exit 0 if the skill is on, 1 if the person switched it off
  disable <skill> | enable <skill>     switch a skill off or on everywhere (~/.mstack/config.json)
  session-start                        the always-on rules for this session (used by the Claude Code plugin hook)
  routing                              the same rules as a block for AGENTS.md or Cursor rules

  log <skill> --outcome reached|partial|not-reached [--needed-user ...] [--stalled ...] [--correction ...] [--note ...]
                                       record privately how one use of a skill went
  review [--skill X] [--json]          gather the journal into evidence for proposed improvements
  learn <skill> "<rule>"               keep an improvement the person accepted (~/.mstack/learned/<skill>.md)
  learned <skill>                      print a skill's accepted improvements (to share one, if the person wants)

  ping "<message>" [--title T]         notify the person now (desktop, plus their own phone service if set up)
  ping hook                            for Claude Code's Notification and Stop hooks (reads the event on stdin)
  ping codex-event '<json>'            for Codex's notify setting
  ping test                            send a test notification
  setup claude-hooks|codex|cursor      show what would be written; add --write after the person says yes
  setup ntfy [--topic T] [--server S]  guided opt-in to a free phone push service; --write after the person says yes
"""
import argparse
import datetime
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))          # the folder holding every mStack skill
SELF = os.path.abspath(__file__)
sys.path.insert(0, HERE)
import rules as rules_file  # noqa: E402  (the rules file per project)
import brief as brief_tool  # noqa: E402  (one line becomes a complete brief)
OUTCOMES = ("reached", "partial", "not-reached")
DEFAULTS = {"disabled": [], "review_every": 10,
            "ping": {"desktop": True, "ntfy_topic": "", "ntfy_server": "https://ntfy.sh"}}


# ---------------------------------------------------------------- home, config, skills

def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, *parts)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    path = home("config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                mine = json.load(fh)
        except ValueError:
            mine = {}
        for k, v in mine.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg):
    os.makedirs(home(), exist_ok=True)
    with open(home("config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def summarise(description):
    """The description's first sentence (or two, if the first is short), at most about 200 characters."""
    parts = re.split(r"(?<=\.)\s+", description.strip())
    text = parts[0]
    if len(text) < 40 and len(parts) > 1:
        text += " " + parts[1]
    if len(text) > 200:
        text = text[:197].rsplit(" ", 1)[0] + "..."
    return text


def skills():
    out = []
    for name in sorted(os.listdir(SKILLS)):
        path = os.path.join(SKILLS, name, "SKILL.md")
        if os.path.exists(path):
            fm = frontmatter(path)
            out.append({"name": fm.get("name", name), "folder": os.path.join(SKILLS, name),
                        "description": fm.get("description", ""), "summary": summarise(fm.get("description", ""))})
    return out


def is_on(name, cfg=None):
    return name not in (cfg or load_config()).get("disabled", [])


def say(args, data, text):
    print(json.dumps(data, indent=2) if getattr(args, "json", False) else text)


def cmd_skills(args):
    cfg = load_config()
    rows = [dict(name=s["name"], on=is_on(s["name"], cfg), summary=s["summary"], folder=s["folder"]) for s in skills()]
    say(args, {"skills": rows, "config": home("config.json")},
        "\n".join("%-16s %-4s %s" % (r["name"], "on" if r["on"] else "off", r["summary"]) for r in rows))


def cmd_enabled(args):
    on = is_on(args.skill)
    print("on" if on else "off: switched off in %s" % home("config.json"))
    sys.exit(0 if on else 1)


def cmd_switch(args):
    cfg = load_config()
    names = [s["name"] for s in skills()]
    if args.skill not in names:
        raise SystemExit("No mStack skill called %r. The skills are: %s" % (args.skill, ", ".join(names)))
    off = [x for x in cfg.get("disabled", []) if x != args.skill]
    if args.command == "disable":
        off.append(args.skill)
    cfg["disabled"] = off
    save_config(cfg)
    print("%s is now %s (%s)" % (args.skill, "off" if args.command == "disable" else "on", home("config.json")))


# ---------------------------------------------------------------- the always-on rules

def journal(name):
    path = home("journal", name + ".jsonl")
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def last_review(name):
    path = home("reviews", "last.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get(name)


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
    print(rules(for_hook=True))


def cmd_routing(args):
    print("<!-- mstack:start -->\n## mStack\n\n%s\n<!-- mstack:end -->" % rules(for_hook=False))


# ---------------------------------------------------------------- journal, review, learn

def cmd_log(args):
    entry = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "skill": args.skill, "outcome": args.outcome,
             "needed_user": args.needed_user, "stalled": args.stalled, "corrections": args.correction, "note": args.note}
    os.makedirs(home("journal"), exist_ok=True)
    with open(home("journal", args.skill + ".jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    say(args, {"ok": True, "uses": len(journal(args.skill))}, "recorded (%d uses of %s so far)" % (
        len(journal(args.skill)), args.skill))


def tally(items):
    counts = {}
    for i in items:
        key = i.strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def cmd_review(args):
    names = [args.skill] if args.skill else [s["name"] for s in skills()]
    report = {}
    for name in names:
        rows = journal(name)
        since = (last_review(name) or {}).get("uses", 0)
        new = rows[since:]
        report[name] = {
            "uses": len(rows), "new_since_last_review": len(new),
            "outcomes": dict((o, sum(1 for r in new if r.get("outcome") == o)) for o in OUTCOMES),
            "needed_user": tally(x for r in new for x in (r.get("needed_user") or [])),
            "stalled": tally(x for r in new for x in (r.get("stalled") or [])),
            "corrections": tally(x for r in new for x in (r.get("corrections") or [])),
            "notes": [r["note"] for r in new if r.get("note")],
            "skill_file": os.path.join(SKILLS, name, "SKILL.md"),
            "learned_file": home("learned", name + ".md"),
        }
    os.makedirs(home("reviews"), exist_ok=True)
    day = datetime.date.today().isoformat()
    path = home("reviews", "%s.md" % day)
    lines = ["# mStack skills review, %s" % day, "",
             "Evidence from the private journal since each skill's last review. For each skill: propose concrete "
             "edits (a rule to add to its learned file, or a change to its SKILL.md), show them to the person, and "
             "keep only the ones they accept with: mstack.py learn <skill> \"<rule>\".", ""]
    for name, r in report.items():
        if not r["new_since_last_review"]:
            continue
        lines += ["## %s: %d new uses (%s)" % (name, r["new_since_last_review"], ", ".join(
            "%s %d" % kv for kv in r["outcomes"].items())), ""]
        for label, key in (("Where it needed the person", "needed_user"), ("Where it stalled", "stalled"),
                           ("The person's corrections", "corrections")):
            if r[key]:
                lines.append("%s:" % label)
                lines += ["- %s (%d)" % kv for kv in r[key]]
                lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    if not args.dry_run:
        marks = {}
        if os.path.exists(home("reviews", "last.json")):
            with open(home("reviews", "last.json"), encoding="utf-8") as fh:
                marks = json.load(fh)
        for name, r in report.items():
            marks[name] = {"uses": r["uses"], "at": day}
        with open(home("reviews", "last.json"), "w", encoding="utf-8") as fh:
            json.dump(marks, fh, indent=2)
    say(args, {"review": path, "skills": report}, "wrote %s" % path)


def cmd_learn(args):
    os.makedirs(home("learned"), exist_ok=True)
    path = home("learned", args.skill + ".md")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# What this person has taught %s\n\nAccepted improvements, newest last. They win over the "
                     "skill's own SKILL.md where the two differ.\n\n" % args.skill)
        fh.write("- %s (%s)\n" % (args.rule.strip(), datetime.date.today().isoformat()))
    print("kept in %s" % path)


def cmd_learned(args):
    path = home("learned", args.skill + ".md")
    if not os.path.exists(path):
        print("Nothing learned yet for %s." % args.skill)
        return
    with open(path, encoding="utf-8") as fh:
        print(fh.read())


# ---------------------------------------------------------------- ping me

def notify(message, title="mStack"):
    """Notify the person: desktop by default, plus their own phone service only if they set one up."""
    cfg = load_config()
    if not is_on("ping-me", cfg):
        return ["off"]
    message = " ".join(str(message).split())[:200]
    sent = []
    override = os.environ.get("MSTACK_NOTIFY_COMMAND")          # for tests and unusual systems
    env = dict(os.environ, MSTACK_TITLE=title, MSTACK_MESSAGE=message)
    if override:
        subprocess.run(override, shell=True, env=env, timeout=20)
        sent.append("command")
    elif cfg["ping"].get("desktop", True):
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            "display notification (item 2 of argv) with title (item 1 of argv) sound name \"Glass\"",
                            "-e", "end run", title, message], capture_output=True, timeout=20)
            sent.append("desktop")
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=20)
            sent.append("desktop")
        elif os.name == "nt" and shutil.which("powershell"):
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                  "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
                  "$n.Visible = $true; $n.ShowBalloonTip(8000, $env:MSTACK_TITLE, $env:MSTACK_MESSAGE, 'Info')")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, timeout=20)
            sent.append("desktop")
    topic = cfg["ping"].get("ntfy_topic")
    if topic:                                                    # opt in only: this sends the text to a third party
        server = cfg["ping"].get("ntfy_server") or "https://ntfy.sh"
        req = urllib.request.Request("%s/%s" % (server.rstrip("/"), topic), data=message.encode("utf-8"),
                                     headers={"Title": title.encode("ascii", "replace").decode()})
        try:
            urllib.request.urlopen(req, timeout=10)
            sent.append("ntfy")
        except Exception as e:
            sent.append("ntfy failed: %s" % e)
    if not sent:
        print("%s: %s" % (title, message))
        sent.append("printed")
    return sent


def cmd_ping(args):
    if args.message == "hook":
        try:
            event = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            event = {}
        where = os.path.basename(event.get("cwd") or "") or "Claude Code"
        kind = event.get("hook_event_name")
        if kind == "Notification":
            notify(event.get("message") or "Claude needs you", "Claude needs you: %s" % where)
        elif kind == "Stop":
            last = " ".join((event.get("last_assistant_message") or "").split())
            notify(last[:160] or "Finished. Back to you.", "Claude finished: %s" % where)
        return
    if args.message == "codex-event":
        try:
            event = json.loads(args.extra or "{}")
        except ValueError:
            event = {}
        if event.get("type") == "agent-turn-complete":
            last = " ".join((event.get("last-assistant-message") or "").split())
            where = os.path.basename(event.get("cwd") or "") or "Codex"
            notify(last[:160] or "Finished. Back to you.", "Codex finished: %s" % where)
        if args.also:                                        # the notify program the person already had: run it too
            try:
                original = json.loads(args.also)
            except ValueError:
                original = None
            if isinstance(original, list) and original and all(isinstance(x, str) for x in original):
                try:
                    subprocess.run(original + [args.extra or "{}"], timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass
        return
    if args.message == "test":
        print("sent: %s" % ", ".join(notify("mStack test: notifications reach you.", "mStack")))
        return
    print("sent: %s" % ", ".join(notify(args.message, args.title)))


# ---------------------------------------------------------------- setup for each agent

def stable_copy():
    """A copy of this tool in ~/.mstack/bin, so hooks keep working when a plugin update moves the original."""
    os.makedirs(home("bin"), exist_ok=True)
    dest = home("bin", "mstack.py")
    shutil.copyfile(SELF, dest)
    return dest


def hook_command(tool):
    return "python3 %s ping hook" % shlex.quote(tool)


def setup_claude(args):
    path = args.settings or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    tool = home("bin", "mstack.py")
    cmd = hook_command(tool)
    entry = {"type": "command", "command": cmd, "async": True}
    want = {"Notification": {"matcher": "permission_prompt|idle_prompt|elicitation_dialog|agent_needs_input",
                             "hooks": [entry]},
            "Stop": {"hooks": [entry]}}
    settings = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            settings = json.load(fh)
    hooks = settings.setdefault("hooks", {})
    changed = []
    for event, group in want.items():
        groups = hooks.setdefault(event, [])
        mine = [g for g in groups if any("mstack.py" in h.get("command", "") and "ping hook" in h.get("command", "")
                                         for h in g.get("hooks", []))]
        if args.remove:
            for g in mine:
                groups.remove(g)
                changed.append("removed %s" % event)
            if not groups:
                hooks.pop(event)
        elif not mine:
            groups.append(group)
            changed.append("added %s" % event)
    if not hooks:
        settings.pop("hooks")
    preview = json.dumps({"hooks": dict((e, want[e]) for e in want)}, indent=2)
    if not args.write:
        print("Would %s these Claude Code hooks in %s:\n%s\nAsk the person; then run again with --write." % (
            "remove" if args.remove else "add", path, preview))
        return
    if not changed:
        print("Nothing to change in %s." % path)
        return
    if not args.remove:
        stable_copy()
    if os.path.exists(path):
        shutil.copyfile(path, path + ".mstack-backup")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    print("%s in %s (backup: %s.mstack-backup)" % (", ".join(changed), path, path))


def setup_codex(args):
    cfg_path = args.codex_config or os.path.join(os.path.expanduser("~"), ".codex", "config.toml")
    agents_path = os.path.join(os.path.dirname(cfg_path), "AGENTS.md")
    tool = home("bin", "mstack.py")
    line = 'notify = ["python3", %s, "ping", "codex-event"]' % json.dumps(tool)
    text = ""
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as fh:
            text = fh.read()
    top = re.split(r"(?m)^\s*\[", text, maxsplit=1)[0]
    has_notify = re.search(r"(?m)^[ \t]*notify[ \t]*=[ \t]*(.*)$", top)
    ours = bool(has_notify) and "mstack.py" in has_notify.group(0)
    previous = None                                          # the person's own notify program, chained if we can read it
    if has_notify and not ours:
        try:
            previous = json.loads(has_notify.group(1).split("#")[0].strip())
        except ValueError:
            previous = None
        if not (isinstance(previous, list) and previous and all(isinstance(x, str) for x in previous)):
            previous = None
        else:
            line = 'notify = ["python3", %s, "ping", "codex-event", "--also", %s]' % (json.dumps(tool), json.dumps(json.dumps(previous)))
    block = "<!-- mstack:start -->\n## mStack\n\n%s\n<!-- mstack:end -->" % rules(for_hook=False)
    if not args.write:
        what = "add to %s (at the top, before any [section])" % cfg_path
        if previous:
            what = "replace the notify line in %s with one that runs mStack's ping and then your own program (%s)" % (
                cfg_path, " ".join(previous))
        elif has_notify and not ours:
            what = ("leave the notify line in %s alone (it could not be read as a list of strings; chain it yourself) "
                    "and would otherwise add" % cfg_path)
        print("Would %s:\n  %s\nand put mStack's routing block in %s (Codex reads that file in every session):\n\n%s\n\n"
              "Ask the person; then run again with --write." % (what, line, agents_path, block))
        return
    stable_copy()
    if not has_notify:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        if os.path.exists(cfg_path):
            shutil.copyfile(cfg_path, cfg_path + ".mstack-backup")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("# mStack ping me: notify when a Codex turn finishes\n%s\n\n%s" % (line, text))
        print("added notify to %s" % cfg_path)
    elif previous:
        shutil.copyfile(cfg_path, cfg_path + ".mstack-backup")
        new_text = text.replace(has_notify.group(0), "# mStack chained the notify program that was here: %s\n%s" % (
            " ".join(previous), line), 1)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        print("chained notify in %s: mStack pings, then your own program runs (backup: %s.mstack-backup)" % (cfg_path, cfg_path))
    elif not ours:
        print("%s already has a notify setting that could not be read; left it alone. To chain mStack, run: %s" % (cfg_path, line))
    write_block(agents_path, block)
    print("routing block in %s" % agents_path)


def write_block(path, block):
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if "<!-- mstack:start -->" in text:
        text = re.sub(r"<!-- mstack:start -->.*?<!-- mstack:end -->", lambda m: block, text, flags=re.S)
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def setup_cursor(args):
    project = os.path.abspath(args.project or ".")
    path = os.path.join(project, ".cursor", "rules", "mstack.mdc")
    body = ("---\ndescription: mStack skills switch on by themselves when relevant\nalwaysApply: true\n---\n\n%s\n"
            % rules(for_hook=False))
    if not args.write:
        print("Would write %s:\n\n%s\nAsk the person; then run again with --write." % (path, body))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print("wrote %s" % path)


def setup_ntfy(args):
    """Opt in to ntfy, a free phone push service: show the change, write it only with --write, then test it."""
    cfg = load_config()
    current = cfg["ping"].get("ntfy_topic") or ""
    if args.remove:
        if not args.write:
            print("Would remove the ntfy topic from %s. Ask the person; then run again with --write." % home("config.json"))
            return
        cfg["ping"]["ntfy_topic"] = ""
        save_config(cfg)
        print("removed the ntfy topic from %s" % home("config.json"))
        return
    topic = args.topic or current or "mstack-" + secrets.token_urlsafe(18)
    server = (args.server or cfg["ping"].get("ntfy_server") or DEFAULTS["ping"]["ntfy_server"]).rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic):
        raise SystemExit("A topic is 8 to 64 letters, digits, - or _ (no spaces), and long enough that nobody can guess it.")
    steps = ("What this does: every ping is also sent, as plain text, to %s/%s. Anyone who knows the topic name can read "
             "it, so it is long and random and must stay private. Never put passwords or private details in a ping.\n"
             "1. On the phone, install the ntfy app (free, open source) and subscribe to the topic: %s\n"
             "2. This writes to %s: {\"ping\": {\"ntfy_topic\": \"%s\", \"ntfy_server\": \"%s\"}}\n"
             "3. Then a test ping is sent, so the person can confirm it arrived." % (
                 server, topic, topic, home("config.json"), topic, server))
    if not args.write:
        print("Would set up phone pings through ntfy.\n%s\nAsk the person; then run again with --write." % steps)
        return
    cfg["ping"]["ntfy_topic"] = topic
    cfg["ping"]["ntfy_server"] = server
    save_config(cfg)
    print("written to %s (topic %s)" % (home("config.json"), topic))
    print("test ping sent: %s" % ", ".join(notify("mStack: phone pings are on. This came through ntfy.", "mStack")))


def cmd_setup(args):
    {"claude-hooks": setup_claude, "codex": setup_codex, "cursor": setup_cursor, "ntfy": setup_ntfy}[args.target](args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("skills")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_skills)
    s = sub.add_parser("enabled")
    s.add_argument("skill")
    s.set_defaults(fn=cmd_enabled)
    for name in ("disable", "enable"):
        s = sub.add_parser(name)
        s.add_argument("skill")
        s.set_defaults(fn=cmd_switch)
    sub.add_parser("session-start").set_defaults(fn=cmd_session_start)
    sub.add_parser("routing").set_defaults(fn=cmd_routing)
    s = sub.add_parser("log")
    s.add_argument("skill")
    s.add_argument("--outcome", required=True, choices=OUTCOMES)
    s.add_argument("--needed-user", action="append", default=[], help="where it needed the person (repeatable)")
    s.add_argument("--stalled", action="append", default=[], help="where it stalled (repeatable)")
    s.add_argument("--correction", action="append", default=[], help="a correction the person made (repeatable)")
    s.add_argument("--note", default="")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_log)
    s = sub.add_parser("review")
    s.add_argument("--skill")
    s.add_argument("--dry-run", action="store_true", help="do not mark the journal as reviewed")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_review)
    s = sub.add_parser("learn")
    s.add_argument("skill")
    s.add_argument("rule")
    s.set_defaults(fn=cmd_learn)
    s = sub.add_parser("learned")
    s.add_argument("skill")
    s.set_defaults(fn=cmd_learned)
    s = sub.add_parser("ping")
    s.add_argument("message", help='the message, or "hook", "codex-event" or "test"')
    s.add_argument("extra", nargs="?", default="", help="the JSON Codex passes to its notify program")
    s.add_argument("--title", default="mStack")
    s.add_argument("--also", help="codex-event: the person's previous notify program, as a JSON list, to run as well")
    s.set_defaults(fn=cmd_ping)
    sub.add_parser("status", help="every project at once, what waits for you first (see status.py)")
    sub.add_parser("rules", help="a rules file per project: init, show, list, import, accept (see rules.py)")
    sub.add_parser("brief", help="one line becomes a complete brief for another agent (see brief.py)")
    s = sub.add_parser("setup")
    s.add_argument("target", choices=("claude-hooks", "codex", "cursor", "ntfy"))
    s.add_argument("--write", action="store_true", help="make the change (only after the person says yes)")
    s.add_argument("--remove", action="store_true", help="claude-hooks or ntfy: take mStack's change out again")
    s.add_argument("--topic", help="ntfy: the private topic name (default: a long random one)")
    s.add_argument("--server", help="ntfy: the server (default https://ntfy.sh)")
    s.add_argument("--settings", help="claude-hooks: the settings file (default ~/.claude/settings.json)")
    s.add_argument("--codex-config", help="codex: the config file (default ~/.codex/config.toml)")
    s.add_argument("--project", help="cursor: the project folder (default: here)")
    s.set_defaults(fn=cmd_setup)
    argv = list(sys.argv[1:] if argv is None else argv)
    also = None
    if argv[:1] == ["ping"] and "--also" in argv:            # Codex puts the event last, after --also <program>
        i = argv.index("--also")
        also = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    if argv[:1] == ["rules"]:                                # a rules file per project: see rules.py
        return rules_file.main(argv[1:])
    if argv[:1] == ["status"]:                               # status across everything: see status.py
        import status as status_view
        return status_view.main(argv[1:])
    if argv[:1] == ["brief"]:                                # one line becomes a brief: see brief.py
        return brief_tool.main(argv[1:])
    args = ap.parse_args(argv)
    if also is not None:
        args.also = also
    args.fn(args)


if __name__ == "__main__":
    main()
