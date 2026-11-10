#!/usr/bin/env python3
"""Every command of outcome.py, away.py, eval_loop.py and direction.py takes --json, prints one JSON document,
and prints its errors as {"ok": false, "error": "..."} with a non-zero exit.

Everything runs in a throwaway folder and a throwaway home (MSTACK_HOME and HOME); no real reviewer, crontab
or notification is touched.

  python3 tests/test_json_commands.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills")
OUTCOME = os.path.join(SK, "outcome-first", "scripts", "outcome.py")
AWAY = os.path.join(SK, "away-mode", "scripts", "away.py")
LOOP = os.path.join(SK, "multi-evaluator", "scripts", "eval_loop.py")
DIRECTION = os.path.join(SK, "design-direction", "scripts", "direction.py")
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def make_env(work):
    fake = os.path.join(work, "fake_crontab.py")
    tab = os.path.join(work, "crontab.txt")
    with open(fake, "w") as fh:
        fh.write("import sys\np=%r\nif sys.argv[1]=='-l':\n    try: print(open(p).read(), end='')\n"
                 "    except OSError: sys.exit(1)\nelse:\n    open(p,'w').write(sys.stdin.read())\n" % tab)
    home = os.path.join(work, "home")
    os.makedirs(home, exist_ok=True)
    return dict(os.environ, MSTACK_HOME=os.path.join(home, ".mstack"), HOME=home, MSTACK_CRONTAB="%s %s" % (sys.executable, fake),
                MSTACK_CHROME="/nonexistent/chrome-for-test")


def call(env, tool, *args, stdin=None):
    """Run a tool; return (exit code, parsed JSON or None, the raw standard output)."""
    r = subprocess.run([sys.executable, tool] + list(args), capture_output=True, text=True, env=env, timeout=120, input=stdin)
    try:
        return r.returncode, json.loads(r.stdout), r.stdout
    except ValueError:
        return r.returncode, None, r.stdout + "|stderr|" + r.stderr


def ok_cmd(env, tool, *args, **kw):
    code, data, raw = call(env, tool, *(list(args) + ["--json"]), **kw)
    check(code == 0 and data is not None, "%s %s --json: one JSON document, exit 0%s" % (
        os.path.basename(tool), " ".join(args[:2]), "" if code == 0 and data is not None else " (got %d: %s)" % (code, raw[:200])))
    return data


def err_cmd(env, tool, *args, **kw):
    code, data, raw = call(env, tool, *(list(args) + ["--json"]), **kw)
    good = code != 0 and isinstance(data, dict) and data.get("ok") is False and data.get("error")
    check(bool(good), "%s %s --json (error path): {\"ok\": false, \"error\"} and a non-zero exit%s" % (
        os.path.basename(tool), " ".join(args[:2]), "" if good else " (got %d: %s)" % (code, raw[:200])))
    return data


def outcome(env, work):
    proj = os.path.join(work, "project")
    os.makedirs(proj)
    err_cmd(env, OUTCOME, "status")                                        # no outcome yet
    ok_cmd(env, OUTCOME, "list")
    err_cmd(env, OUTCOME, "new", "No checks")                               # needs --done
    ok_cmd(env, OUTCOME, "new", "Ships", "--slug", "ships", "--cwd", proj, "--done", "It exists::true",
           "--resume-command", "true")
    ok_cmd(env, OUTCOME, "status", "ships")
    ok_cmd(env, OUTCOME, "task", "add", "ships", "Build it")
    err_cmd(env, OUTCOME, "task", "set", "ships", "t1", "--state", "done")   # done needs evidence
    ok_cmd(env, OUTCOME, "task", "set", "ships", "t1", "--state", "doing")
    ok_cmd(env, OUTCOME, "ready", "ships")
    ok_cmd(env, OUTCOME, "ask", "ships", "Which colour?", "--default", "blue")
    ok_cmd(env, OUTCOME, "questions", "ships")
    ok_cmd(env, OUTCOME, "answer", "ships", "q1", "blue")
    ok_cmd(env, OUTCOME, "note", "ships", "a note")
    code, data, raw = call(env, OUTCOME, "check", "ships", "--json")       # not achieved: still one JSON document
    check(code == 1 and data is not None and data["achieved"] is False, "check --json: JSON on stdout, exit 1 while not achieved")
    err_cmd(env, OUTCOME, "verify", "ships", "d9", "--evidence", "x")
    err_cmd(env, OUTCOME, "verify", "ships", "d1", "--evidence", "x")        # proved by a command
    ok_cmd(env, OUTCOME, "schedule", "ships", "--in-minutes", "5", "--dry-run")
    ok_cmd(env, OUTCOME, "schedule", "ships", "--in-minutes", "5")
    ok_cmd(env, OUTCOME, "unschedule", "ships")
    err_cmd(env, OUTCOME, "schedule", "missing", "--in-minutes", "5")
    err_cmd(env, OUTCOME, "task")                                           # a usage error is JSON too
    ok_cmd(env, OUTCOME, "task", "set", "ships", "t1", "--state", "done", "--evidence", "built")
    code, data, raw = call(env, OUTCOME, "check", "ships", "--json")
    check(code == 0 and data and data["achieved"] is True, "check --json: achieved when everything passes")
    ok_cmd(env, OUTCOME, "resume", "ships")                                 # already achieved: still JSON
    check(True, "outcome.py walked")


def away(env, work):
    ok_cmd(env, AWAY, "status")
    ok_cmd(env, AWAY, "status", "--hint", "the user is at the terminal")
    ok_cmd(env, AWAY, "set", "away", "--hours", "1")
    ok_cmd(env, AWAY, "set", "back")
    ok_cmd(env, AWAY, "heard", "I'm on my phone")
    data = ok_cmd(env, AWAY, "outbox")
    check(bool(data) and data.get("ok") is True and "outbox" in data, "away.py outbox --json names the outbox folder")
    out = os.path.join(work, "copies")
    err_cmd(env, AWAY, "render", os.path.join(work, "no-such-file.html"), "--out", out)
    page = os.path.join(work, "page.html")
    with open(page, "w") as fh:
        fh.write("<html><body><p>hello</p></body></html>")
    code, data, raw = call(env, AWAY, "render", page, "--out", out, "--json")
    check(data is not None, "away.py render --json: JSON whether or not a renderer exists (exit %d)" % code)
    err_cmd(env, AWAY, "set", "sideways")                                   # a usage error is JSON too


def evaluator(env, work):
    rev = os.path.join(work, "review")
    d = ["--dir", rev]
    err_cmd(env, LOOP, "status", *d)                                        # no config
    for cmd in ("start-round", "capture", "brief", "review", "report", "notify", "serve"):
        err_cmd(env, LOOP, cmd, *d)
    err_cmd(env, LOOP, "verdict", "--reviewer", "claude", "-", *d, stdin="{}")
    err_cmd(env, LOOP, "validate", "-", *d, stdin="{}")
    ok_cmd(env, LOOP, "init", "--name", "Test product", *d)
    err_cmd(env, LOOP, "init", *d)                                          # already there
    ok_cmd(env, LOOP, "status", *d)
    err_cmd(env, LOOP, "brief", *d)                                         # no round yet
    ok_cmd(env, LOOP, "start-round", *d)
    cfgp = os.path.join(rev, "mstack-eval.json")
    with open(cfgp) as fh:
        cfg = json.load(fh)
    cfg["reviewers"] = [{"id": "claude", "name": "Claude", "kind": "agent"}, {"id": "other", "name": "Other", "kind": "agent"}]
    with open(cfgp, "w") as fh:
        json.dump(cfg, fh)
    shots = os.path.join(rev, "rounds", "r1", "shots")
    os.makedirs(shots, exist_ok=True)
    with open(os.path.join(shots, "home-desktop.png"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
    ok_cmd(env, LOOP, "brief", *d)
    ok_cmd(env, LOOP, "review", *d)                                         # agent reviewers: nothing to run
    err_cmd(env, LOOP, "verdict", "--reviewer", "nobody", "-", *d, stdin="{}")
    code, data, raw = call(env, LOOP, "validate", "-", *d, "--json", stdin="{}")
    check(code == 1 and data is not None and data.get("ok") is False, "validate --json: JSON problems and exit 1 on a bad reply")
    code, data, raw = call(env, LOOP, "verdict", "--reviewer", "claude", "-", *d, "--json", stdin="{}")
    check(code == 1 and data is not None and data.get("ok") is False, "verdict --json: JSON problems and exit 1 on a bad reply")
    ok_cmd(env, LOOP, "notify", *d)
    code, data, raw = call(env, LOOP, "report", *d, "--json", "--no-notify")
    check(data is not None, "report --json prints JSON (exit %d)" % code)
    err_cmd(env, LOOP, "start-round", "--dir", os.path.join(work, "nowhere"))
    err_cmd(env, LOOP, "frobnicate", *d)                                    # an unknown command is JSON too


def direction(env, work):
    dd = os.path.join(work, "dir")
    d = ["--dir", dd]
    os.makedirs(dd)
    for cmd in ("status", "options", "narrow", "shots", "compare", "lock", "pick"):
        err_cmd(env, DIRECTION, cmd, *d)                                    # no direction.json yet
    ok_cmd(env, DIRECTION, "init", "--name", "Sample", "--taste", "calm and clear", *d)
    err_cmd(env, DIRECTION, "init", "--name", "Sample", *d)                  # already there
    ok_cmd(env, DIRECTION, "status", *d)
    err_cmd(env, DIRECTION, "pick", *d)                                     # says neither option nor variant
    err_cmd(env, DIRECTION, "pick", "--option", "a", *d)                    # no such built file
    err_cmd(env, DIRECTION, "shots", *d)                                    # no round yet
    err_cmd(env, DIRECTION, "init", *d)                                     # --name is required: a usage error


def main():
    work = tempfile.mkdtemp(prefix="mstack-json-test-")
    try:
        env = make_env(work)
        for fn in (outcome, away, evaluator, direction):
            sub = os.path.join(work, fn.__name__)
            os.makedirs(sub)
            fn(env, sub)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("every command speaks JSON" if not failures else "FAILED: %d" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
