#!/usr/bin/env python3
"""Self-test for outcome-first: the durable plan, parallel waves, one batch of questions, evidence-based done
checks, and resuming after a usage limit through a stand-in crontab.

Everything runs in a throwaway folder (MSTACK_HOME), and MSTACK_CRONTAB points at a stand-in that keeps
the "crontab" in a file, so the computer's real crontab is never touched.

  python3 tests/test_outcome.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "skills", "outcome-first", "scripts", "outcome.py")
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def main():
    work = tempfile.mkdtemp(prefix="mstack-outcome-test-")
    project = os.path.join(work, "project")
    os.makedirs(project)
    tab = os.path.join(work, "crontab.txt")
    fake = os.path.join(work, "fake_crontab.py")
    with open(fake, "w") as fh:
        fh.write("import sys\np=%r\nif sys.argv[1]=='-l':\n    try: print(open(p).read(), end='')\n"
                 "    except OSError: sys.exit(1)\nelse:\n    open(p,'w').write(sys.stdin.read())\n" % tab)
    env = dict(os.environ, MSTACK_HOME=os.path.join(work, "home"), MSTACK_CRONTAB="%s %s" % (sys.executable, fake))

    def run(*args, expect=0):
        r = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != expect:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  outcome.py %s exited %d, expected %d" % (" ".join(args), r.returncode, expect))
        return r.stdout

    def js(*args, expect=0):
        return json.loads(run(*(list(args) + ["--json"]), expect=expect))

    try:
        r = subprocess.run([sys.executable, TOOL, "new", "Ships"], capture_output=True, text=True, env=env)
        check(r.returncode != 0 and "what done looks like" in (r.stdout + r.stderr), "an outcome needs what done looks like")

        s = js("new", "The notes app ships with export", "--cwd", project, "--slug", "notes",
               "--done", "The export file exists::test -f export.txt",
               "--done", "The person can open the export in their editor",
               "--resume-command", "echo resumed >> resumed.txt")
        check(s["slug"] == "notes" and os.path.exists(s["progress_file"]), "new writes the durable progress file")
        check("Plan" in s["next"], "the first next step is to plan")
        for title, after in (("Write export", ""), ("Write tests", ""), ("Ship", "t1,t2")):
            run("task", "add", "notes", title, *(["--after", after] if after else []))
        run("task", "add", "notes", "Bad", "--after", "t9", expect=1)
        check(True, "a task cannot wait for one that does not exist")
        ready = [t["id"] for t in js("ready", "notes")["ready"]]
        check(ready == ["t1", "t2"], "independent tasks are ready together, for parallel work")
        run("task", "set", "notes", "t1", "--state", "done", expect=1)
        check(True, "a task is not done without evidence")
        run("task", "set", "notes", "t1", "--state", "done", "--evidence", "export.py written")
        check([t["id"] for t in js("ready", "notes")["ready"]] == ["t2"], "a task waits until what it is after is done")
        run("task", "set", "notes", "t2", "--state", "done", "--evidence", "4 tests pass")
        check([t["id"] for t in js("ready", "notes")["ready"]] == ["t3"], "the next wave opens")

        js("ask", "notes", "Which file format?", "--default", "Markdown")
        js("ask", "notes", "Ship tonight or tomorrow?", "--default", "Tonight")
        qs = js("questions", "notes")["questions"]
        check([q["id"] for q in qs] == ["q1", "q2"] and qs[0]["default"] == "Markdown",
              "questions queue up with defaults, to ask in one batch")
        run("answer", "notes", "q1", "Markdown")
        check(js("status", "notes")["open_questions"] == ["q2"], "answers close questions")

        s = js("check", "notes", expect=1)
        check(not s["achieved"] and s["unfinished_tasks"] == ["t3"], "not achieved while a task is unfinished")
        check([t["id"] for t in s["open_tasks"]] == ["t3"] and s["open_tasks"][0]["title"] == "Ship",
              "check --json lists the open tasks")
        text = run("check", "notes", expect=1)
        check("Open tasks:" in text and "t3  Ship" in text and "task set notes <id> --state done" in text,
              "check names each open task and the command that marks one done")
        run("task", "set", "notes", "t3", "--state", "done", "--evidence", "tagged v1.0")
        s = js("check", "notes", expect=1)
        check(not s["achieved"] and s["done_checks"][0]["result"] == "fail", "a failing proof keeps it from being achieved")
        open(os.path.join(project, "export.txt"), "w").write("notes")
        s = js("check", "notes", expect=1)
        check(s["done_checks"][0]["result"] == "pass" and not s["achieved"],
              "a check with no command still needs evidence")
        run("verify", "notes", "d2", "--evidence", "Opened export.txt in TextEdit; both notes there.")
        s = js("check", "notes", expect=1)
        check(not s["achieved"] and s["open_questions"] == ["q2"], "not achieved while a question for the person is open")
        check("still open (q2)" in run("check", "notes", expect=1), "check says which question is open and how to take the defaults")
        js("ask", "notes", "Name of the release?")
        s = js("answer", "notes", "--defaults")
        check(s["taken"] == ["q2"] and s["still_open"] == ["q3"], "answer --defaults takes the defaults and leaves questions without one open")
        check("the default; nobody could answer" in open(s["progress_file"]).read(), "the taken defaults are visible in the progress file")
        run("answer", "notes", "q3", "v1")
        s = js("check", "notes")
        check(s["achieved"] and s["state"] == "achieved" and "Report once" in s["next"],
              "achieved only when every task is done, every check has evidence and no question is open")
        check("progress file:" in run("check", "notes"), "check names the progress file")
        md = open(s["progress_file"]).read()
        check("State: **achieved**" in md and "[x] d1" in md and "Evidence:" in md, "the progress file shows the evidence")

        # resuming after a usage limit
        js("new", "Second outcome", "--cwd", project, "--slug", "second", "--done", "x::true",
           "--resume-command", "echo resumed >> resumed.txt")
        dry = js("schedule", "second", "--in-minutes", "300", "--dry-run")
        check("# mstack-resume:second" in dry["line"] and not os.path.exists(tab), "schedule --dry-run only shows the line")
        check("export PATH=" in dry["line"] and "export MSTACK_HOME=" in dry["line"] and dry["program"].endswith("echo"),
              "the cron line carries this PATH and home, and the resume program was found")
        js("new", "Unrunnable", "--cwd", project, "--slug", "unrunnable", "--done", "x::true",
           "--resume-command", "no-such-program-for-mstack --go")
        r = subprocess.run([sys.executable, TOOL, "schedule", "unrunnable", "--in-minutes", "5", "--dry-run"],
                           capture_output=True, text=True, env=env)
        check(r.returncode != 0 and "not on this PATH" in (r.stdout + r.stderr) and not os.path.exists(tab),
              "a resume command whose program cannot be found is refused")
        open(tab, "w").write("0 9 * * 1 echo the person's own job\n")
        js("schedule", "second", "--in-minutes", "300")
        text = open(tab).read()
        check("the person's own job" in text and text.count("mstack-resume:second") == 1,
              "schedule adds one line and keeps the person's own")
        js("schedule", "second", "--at", "2030-01-02 03:04")
        text = open(tab).read()
        check(text.count("mstack-resume:second") == 1 and text.splitlines()[-1].startswith("4 3 2 1 *"),
              "rescheduling replaces the line")
        check("Resume scheduled for 2030-01-02T03:04" in open(os.path.join(work, "home", "outcomes", "second",
                                                                           "progress.md")).read(),
              "the progress file says when it resumes")
        run("resume", "second")
        check(open(os.path.join(project, "resumed.txt")).read() == "resumed\n", "resume runs the saved resume command")
        check("mstack-resume" not in open(tab).read() and "the person's own job" in open(tab).read(),
              "resume removes its own line, so it never runs twice")
        listed = js("list")["outcomes"]
        check(sorted(o["slug"] for o in listed) == ["notes", "second", "unrunnable"], "list shows every outcome")
        check(js("status")["slug"] == "second", "status with no name shows the latest outcome")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
