#!/usr/bin/env python3
"""Every subcommand of every public tool answers --json with one JSON value on standard output.

The list of subcommands is read from each tool's own argument parser, so a command added tomorrow is covered
the day it is added. Each command runs on its own, in a fresh throwaway home and an empty folder, with the
arguments it must have filled in (a missing folder, an unknown name, or a dry run where one exists), so nothing
starts an agent, a browser, a server or a background job. Notifications go to a stand-in command.

  python3 tests/test_json_everywhere.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills")
# label, scripts folder, module, how to get the parser(s)
TOOLS = [
    ("mstack", "mstack", "mstack", "build_parser"),
    ("mstack rules", "mstack", "rules", "main"),
    ("mstack status", "mstack", "status", "main"),
    ("mstack brief", "mstack", "brief", "main"),
    ("away", "away-mode", "away", "main"),
    ("outcome", "outcome-first", "outcome", "main"),
    ("crew", "crew", "crew", "main"),
    ("eval_loop", "multi-evaluator", "eval_loop", "main"),
    ("direction", "design-direction", "direction", "main"),
]
SCRIPTS = {"mstack": "mstack.py", "away": "away.py", "outcome": "outcome.py", "crew": "crew.py",
           "eval_loop": "eval_loop.py", "direction": "direction.py"}
# Extra arguments for commands that would otherwise do real work: a dry run, or no sending.
SAFE = {"crew run": ["--dry-run"], "crew install": ["--dry-run"], "crew uninstall": ["--dry-run"],
        "crew digest": ["--no-send"], "outcome schedule": ["--dry-run"]}
failures = []

# Runs inside a child process: load one tool, catch the parser it builds, and print every leaf command.
WALK = r'''
import argparse, importlib, json, sys
folder, module, how = sys.argv[1:4]
sys.path.insert(0, folder)
mod = importlib.import_module(module)

class Got(Exception):
    pass

def grab(self, *a, **k):
    raise Got(self)

argparse.ArgumentParser.parse_args = grab
try:
    root = mod.build_parser() if how == "build_parser" else mod.main([]) if module != "direction" else mod.main()
except Got as g:
    root = g.args[0]

def value(a):
    if a.choices:
        return str(list(a.choices)[0])
    return "1" if a.type in (int, float) else "x"

def leaf(p, path):
    argv = []
    picked = set()
    for g in p._mutually_exclusive_groups:
        if g.required and g._group_actions:
            picked.add(g._group_actions[0])
    for a in p._actions:
        if isinstance(a, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if a.option_strings:
            if a.required or a in picked:
                argv += [a.option_strings[0]] + ([] if a.nargs == 0 else [value(a)])
        elif a.nargs not in ("?", "*"):
            argv += [value(a)]
    has_json = any("--json" in a.option_strings for a in p._actions)
    return {"path": path, "argv": argv, "json": has_json}

def walk(p, path, out):
    subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        out.append(leaf(p, path))
        return
    for name, sp in subs[0].choices.items():
        walk(sp, path + [name], out)

found = []
walk(root, [], found)
print(json.dumps(found))
'''


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def commands(env, work):
    """[(label, tool script, argv)] read from each tool's own parser."""
    out = []
    for label, folder, module, how in TOOLS:
        scripts = os.path.join(SK, folder, "scripts")
        r = subprocess.run([sys.executable, "-c", WALK, scripts, module, how], capture_output=True, text=True, env=env,
                           cwd=work, timeout=120)
        try:
            leaves = json.loads(r.stdout)
        except ValueError:
            check(False, "%s: could read the subcommands from the tool's own parser (%s)" % (label, r.stderr.strip()[-200:]))
            continue
        top = label.split()[0]
        script = os.path.join(scripts, SCRIPTS[top])
        for leaf in leaves:
            if label == "mstack" and leaf["path"][:1] in (["status"], ["rules"], ["brief"]):
                continue                                 # stand-ins in mstack.py's own parser: the tools' parsers follow
            name = " ".join([label] + leaf["path"])
            prefix = label.split()[1:] if len(label.split()) > 1 else []
            out.append((name, script, prefix + leaf["path"] + leaf["argv"] + SAFE.get(name, []), leaf["json"]))
    return out


def main():
    base = os.path.realpath(tempfile.mkdtemp(prefix="mstack-json-"))
    n = 0
    try:
        probe = os.path.join(base, "probe")
        os.makedirs(probe)
        tools = commands(dict(os.environ), probe)
        check(len(tools) >= 50, "the walk found %d commands across the tools' own parsers" % len(tools))
        labels = [t[0] for t in tools]
        for must in ("mstack skills", "mstack rules init", "mstack status", "mstack brief", "mstack catalog", "mstack unlearn",
                     "away render", "outcome schedule", "crew branches", "eval_loop capture", "direction lock"):
            check(must in labels, "the walk covers %s" % must)
        for name, script, argv, has_json in tools:
            n += 1
            work = os.path.join(base, "run%03d" % n)
            home = os.path.join(work, "home")
            project = os.path.join(work, "project")
            os.makedirs(project)
            os.makedirs(home)
            fake_tab = os.path.join(work, "no-crontab")
            env = dict(os.environ, HOME=home, MSTACK_HOME=os.path.join(home, ".mstack"), CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"),
                       CODEX_HOME=os.path.join(home, ".codex"), MSTACK_NOTIFY_COMMAND="true", MSTACK_CRONTAB=fake_tab,
                       MSTACK_CHROME="/nonexistent/chrome-for-test")
            if not has_json:
                check(False, "%s takes --json" % name)
                continue
            try:
                r = subprocess.run([sys.executable, script] + argv + ["--json"], capture_output=True, text=True, env=env,
                                   cwd=project, timeout=90, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                check(False, "%s --json: answered within 90 seconds" % name)
                continue
            try:
                data = json.loads(r.stdout)
                good = True
            except ValueError:
                data, good = None, False
            ok = good and not (isinstance(data, dict) and data.get("ok") is False and r.returncode == 0)
            check(ok, "%s --json: one JSON value%s" % (name, "" if ok else " (exit %d, stdout: %r, stderr: %r)" % (
                r.returncode, r.stdout[:160], r.stderr.strip()[-160:])))
            if good and r.returncode != 0 and not isinstance(data, dict):
                check(False, "%s --json: a failure is a JSON object" % name)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
