#!/usr/bin/env python3
"""The launcher in <mstack home>/bin survives updates: hooks, the Codex notify line and the routing block written into
another agent's instructions keep working after the skills folder moves, and a plain read never writes.

Everything runs in a throwaway folder: MSTACK_HOME, HOME, CLAUDE_CONFIG_DIR and CODEX_HOME point there and
notifications go to a stand-in command.

  python3 tests/test_launcher.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def main():
    work = os.path.realpath(tempfile.mkdtemp(prefix="mstack-launcher-"))
    sent = os.path.join(work, "sent.txt")
    fake = os.path.join(work, "fake")
    mhome = os.path.join(fake, ".mstack")
    os.makedirs(fake)
    env = dict(os.environ, HOME=fake, MSTACK_HOME=mhome, CLAUDE_CONFIG_DIR=os.path.join(fake, ".claude"),
               CODEX_HOME=os.path.join(fake, ".codex"),
               MSTACK_NOTIFY_COMMAND='printf "%%s\\n" "$MSTACK_MESSAGE" >> %s' % sent)
    stop = json.dumps({"hook_event_name": "Stop", "cwd": os.path.join(work, "project")})

    def go(*cmd, stdin=None):
        r = subprocess.run([sys.executable] + list(cmd), capture_output=True, text=True, env=env, input=stdin, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def tool_in(root):
        return os.path.join(root, "skills", "mstack", "scripts", "mstack.py")

    def pings():
        return open(sent).read().count("\n") if os.path.exists(sent) else 0

    def snapshot():
        return {p: os.stat(p).st_mtime_ns for p in (os.path.join(mhome, "install.json"), os.path.join(mhome, "bin", "mstack.py"))}

    try:
        launcher = os.path.join(mhome, "bin", "mstack.py")
        first = os.path.join(work, "cache", "0.7.1")                        # a plugin cache folder with a version in it
        os.makedirs(first)
        shutil.copytree(os.path.join(ROOT, "skills"), os.path.join(first, "skills"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(ROOT, ".claude-plugin"), os.path.join(first, ".claude-plugin"))

        # a plain read-only command never writes
        for args in (["skills", "--json"], ["routing"], ["catalog", "--check"], ["status", "--json"], ["rules", "show", "--json"]):
            go(tool_in(first), *args)
        check(not os.path.exists(os.path.join(mhome, "install.json")) and not os.path.exists(os.path.join(mhome, "bin")),
              "skills, routing, catalog, status and rules show write no install record and no launcher")

        # session-start makes install.json and the launcher, and only when they would change
        code, out, _ = go(tool_in(first), "session-start")
        rec = json.load(open(os.path.join(mhome, "install.json")))
        check(code == 0 and rec["root"] == first and rec["version"], "session-start writes install.json with the root and the version")
        check(os.listdir(os.path.join(mhome, "bin")) == ["mstack.py"], "the bin folder holds only the launcher")
        snap = snapshot()
        time.sleep(0.05)
        go(tool_in(first), "session-start")
        check(snapshot() == snap, "a second session-start writes nothing, because nothing changed")

        # setup writes a hook, a notify line and the routing block through the launcher
        settings, codex = os.path.join(work, "settings.json"), os.path.join(work, "codex", "config.toml")
        go(tool_in(first), "setup", "claude-hooks", "--settings", settings, "--write")
        go(tool_in(first), "setup", "codex", "--codex-config", codex, "--write")
        hook = json.load(open(settings))["hooks"]["Stop"][0]["hooks"][0]["command"]
        notify_line = open(codex).read()
        block = open(os.path.join(work, "codex", "AGENTS.md")).read()
        check(launcher in hook and launcher in notify_line, "the hook and the Codex notify line point at the launcher")
        check("0.7.1" not in block and first not in block and "/cache/" not in block,
              "the routing block written for Codex carries no path into the folder mStack ran from")
        check(launcher in block and "where ping-me" in block and "tool away-mode away.py status" in block,
              "the routing block uses the launcher, `where` and `tool` for every command")

        # an old style hook (the whole tool copied into bin by 0.7.1 or the first fix) is replaced by the launcher
        for name in ("rules.py", "mbase.py", "notify.py"):
            shutil.copy(os.path.join(first, "skills", "mstack", "scripts", name), os.path.join(mhome, "bin", name))
        os.makedirs(os.path.join(mhome, "bin", "__pycache__"))
        go(tool_in(first), "session-start")
        check(os.listdir(os.path.join(mhome, "bin")) == ["mstack.py"], "session-start clears copies of the modules from the bin folder")

        # the skills folder moves to a new place (a plugin update)
        second = os.path.join(work, "cache", "0.7.2")
        os.rename(first, second)
        code, out, err = go(launcher, "skills")
        check(code == 1 and "cannot find its install" in out and len(out.strip().splitlines()) == 1,
              "after the move, before any refresh, the launcher says how to repair it in one line")
        code, out, err = go(launcher, "skills", "--json")
        check(json.loads(out)["ok"] is False, "the repair message is JSON with --json")
        n = pings()
        code, out, err = go(launcher, "ping", "hook", stdin=stop)
        check(code == 0 and out == "" and err == "" and pings() == n, "a stale hook exits 0 and says nothing")
        code, out, err = go(launcher, "ping", "codex-event", json.dumps({"type": "agent-turn-complete"}))
        check(code == 0 and out == "" and err == "", "a stale Codex notify line exits 0 and says nothing")

        go(tool_in(second), "session-start")
        check(json.load(open(os.path.join(mhome, "install.json")))["root"] == second, "session-start from the new place updates install.json")
        n = pings()
        code, out, err = go(launcher, "ping", "hook", stdin=stop)
        check(code == 0 and pings() == n + 1, "the hook written before the move still pings, through the launcher")
        old = re.search(r'notify = \["python3", "([^"]+)", "ping", "codex-event"\]', notify_line)
        code, out, err = go(old.group(1), "ping", "codex-event", json.dumps({"type": "agent-turn-complete", "cwd": work}))
        check(code == 0 and pings() == n + 2, "the Codex notify line written before the move still pings")
        paths = re.findall(r"python3 (\S+) where ping-me", block)
        code, out, err = go(paths[0], "where", "ping-me")
        check(code == 0 and out.strip() == os.path.join(second, "skills", "ping-me", "SKILL.md"),
              "the routing block's `where` command finds a skill after the move")
        code, out, err = go(launcher, "where", "--json")
        check(json.loads(out) == {"ok": True, "path": second}, "where prints the folder holding skills (JSON too)")
        code, out, err = go(launcher, "where", "nope", "--json")
        check(code == 1 and json.loads(out)["ok"] is False, "where for an unknown skill is a JSON error with exit 1")
        code, out, err = go(launcher, "tool", "away-mode", "away.py", "status", "--text")
        check(code == 0 and out.startswith(("away", "present", "unsure")), "tool runs another skill's script")
        code, out, err = go(launcher, "enabled", "no-such-skill", "--json")
        check(code == 2 and json.loads(out)["ok"] is False, "the launcher passes the real tool's exit code and JSON through")

        # a root with a version in it never leaks into the routing block for other agents
        third = os.path.join(work, "x", "0.7.1")
        os.makedirs(third)
        shutil.copytree(os.path.join(second, "skills"), os.path.join(third, "skills"))
        code, out, err = go(tool_in(third), "routing")
        check(code == 0 and "0.7.1" not in out and third not in out, "routing from a root under /x/0.7.1/ carries no such path")
        code, out, err = go(tool_in(third), "session-start")
        check("/x/0.7.1/" in out, "the session start note may keep direct paths, because it is rebuilt every session")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
