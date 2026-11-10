#!/usr/bin/env python3
"""The mStack launcher. mStack keeps one copy of this file at <mstack home>/bin/mstack.py. Hooks, notify lines and
the routing block in other agents' instructions point at it, so they keep working when a plugin update moves the
real tool. It imports nothing from mStack: it reads <mstack home>/install.json and runs the real tool.

  mstack.py <any mstack.py command ...>        run the real tool with the same arguments, input and exit code
  mstack.py tool <skill> <script> [args ...]   run another skill's script, for example: tool away-mode away.py status
  mstack.py where [<skill>]                    print the folder holding skills/, or a skill's SKILL.md (add --json)

When install.json is missing or points at a folder that is gone, it prints one line saying how to repair it and
exits 1. For `ping hook` and `ping codex-event` it exits 0 quietly, so a stale hook never blocks an agent's turn.
"""
import json
import os
import sys


def say_error(message, as_json):
    print(json.dumps({"ok": False, "error": message}) if as_json else message)
    sys.exit(1)


def main(argv):
    home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    as_json = "--json" in argv
    quiet = argv[:2] in (["ping", "hook"], ["ping", "codex-event"])
    record = os.path.join(home, "install.json")
    try:
        with open(record, encoding="utf-8") as fh:
            root = json.load(fh)["root"]
        if not os.path.isdir(os.path.join(root, "skills")):
            raise ValueError("gone")
    except (OSError, ValueError, KeyError, TypeError):
        if quiet:
            sys.exit(0)
        say_error("mStack cannot find its install (%s is missing or points at a folder that is gone). To repair it, run "
                  "`python3 <the installed mStack folder>/skills/mstack/scripts/mstack.py session-start`, or run "
                  "`setup` again with --write." % record, as_json)
    skills = os.path.join(root, "skills")
    if argv[:1] == ["where"]:
        names = [a for a in argv[1:] if a != "--json"]
        path = root if not names else os.path.join(skills, names[0], "SKILL.md")
        if names and (os.sep in names[0] or not os.path.exists(path)):
            say_error("No mStack skill called %r." % names[0], as_json)
        print(json.dumps({"ok": True, "path": path}) if as_json else path)
        return
    if argv[:1] == ["tool"]:
        if len(argv) < 3 or any(os.sep in a or a.startswith(".") for a in argv[1:3]):
            say_error("Usage: mstack.py tool <skill> <script name> [args ...]", as_json)
        script = os.path.join(skills, argv[1], "scripts", argv[2])
        rest = argv[3:]
    else:
        script = os.path.join(skills, "mstack", "scripts", "mstack.py")
        rest = argv
    if not os.path.isfile(script):
        say_error("mStack has no script %s." % script, as_json)
    sys.stdout.flush()
    command = [sys.executable, script] + rest
    if os.name == "nt":                              # Windows has no true exec: run it and pass the exit code on
        import subprocess
        sys.exit(subprocess.call(command))
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main(sys.argv[1:])
