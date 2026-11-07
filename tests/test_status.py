#!/usr/bin/env python3
"""Self-test for `mstack status`: one view across every project mStack knows.

Everything runs in a throwaway folder (MSTACK_HOME, CODEX_HOME). Project A is a git repository with one commit and
a tag; project B is a plain folder with a HANDOFF.md. No model, no network.

  python3 tests/test_status.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
MSTACK = os.path.join(SKILLS, "mstack", "scripts", "mstack.py")
STATUS = os.path.join(SKILLS, "mstack", "scripts", "status.py")
OUTCOME = os.path.join(SKILLS, "outcome-first", "scripts", "outcome.py")
RULES = os.path.join(SKILLS, "mstack", "scripts", "rules.py")
sys.path.insert(0, os.path.join(SKILLS, "crew", "scripts"))
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def main():
    work = tempfile.mkdtemp(prefix="mstack-status-test-")
    home = os.path.join(work, "home")
    a, b = os.path.join(work, "proj-a"), os.path.join(work, "proj-b")
    os.makedirs(a)
    os.makedirs(b)
    env = dict(os.environ, MSTACK_HOME=home, CODEX_HOME=os.path.join(work, "codex"), MSTACK_CREW_AWAY="0")

    def run(script, *args, expect=0):
        r = subprocess.run([sys.executable, script] + list(args), capture_output=True, text=True, env=env, timeout=300)
        if r.returncode != expect:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  %s %s exited %d, expected %d" % (os.path.basename(script), " ".join(args), r.returncode, expect))
        return r.stdout

    def status(*args):
        return run(MSTACK, "status", *args)

    try:
        git = ["git", "-C", a, "-c", "user.name=t", "-c", "user.email=t@localhost"]
        subprocess.run(["git", "-C", a, "init", "-q", "-b", "main"], check=True)
        with open(os.path.join(a, "f.txt"), "w") as fh:
            fh.write("x\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "first"], check=True)
        subprocess.run(git + ["tag", "-a", "v0.1.0", "-m", "first release"], check=True)
        with open(os.path.join(b, "HANDOFF.md"), "w") as fh:
            fh.write("# Handoff\n\n## State\n\nLine one of the state.\nLine two.\n\nLine three.\nLine four.\n\n## Next\n- x\n")
        # outcomes: A has an open question with a default; B has every task done and one doing
        run(OUTCOME, "new", "Ship A", "--done", "it works", "--slug", "ship-a", "--cwd", a)
        run(OUTCOME, "ask", "ship-a", "Which name?", "--default", "Plain")
        run(OUTCOME, "new", "Ship B", "--done", "it works", "--slug", "ship-b", "--cwd", b)
        run(OUTCOME, "task", "add", "ship-b", "First")
        run(OUTCOME, "task", "add", "ship-b", "Second")
        run(OUTCOME, "task", "set", "ship-b", "t1", "--state", "done", "--evidence", "seen")
        run(OUTCOME, "task", "set", "ship-b", "t2", "--state", "doing")
        # crew: A is a project, one running job, one open question
        import crew_store as cst
        os.makedirs(os.path.join(home, "crew"))
        with open(os.path.join(home, "crew", "config.json"), "w") as fh:
            json.dump({"projects": [{"id": "proja", "path": a}]}, fh)
        job = cst.new_job("proja", "Tidy the readme", tier="small")
        job.update(state="doing", started="2026-11-08T07:00:00", runner_used="claude")
        asked = cst.new_job("proja", "Pick a colour", tier="small")
        asked.update(state="question", question="Which colour?", default="blue")
        queue = {"jobs": [job, asked], "questions": [
            {"key": "job-" + asked["id"], "job": asked["id"], "project": "proja", "asked": cst.stamp(), "answer": "",
             "question": "Which colour?", "default": "blue"}]}
        with open(os.path.join(home, "crew", "queue.json"), "w") as fh:
            json.dump(queue, fh)
        run(RULES, "init", "--project", b)
        # a review folder for B with the smallest config and no rounds
        rev = os.path.join(home, "reviews", "b-design")
        os.makedirs(rev)
        with open(os.path.join(rev, "mstack-eval.json"), "w") as fh:
            json.dump({"name": "B design", "project": b, "journeys": [{"id": 1, "name": "One", "task": "Do it."}],
                       "views": [], "reviewers": [{"id": "x", "name": "X", "kind": "agent"}]}, fh)

        data = json.loads(status("--json"))
        projects = data["projects"]
        check(len(projects) == 2 and all(p.get("path") and p.get("name") for p in projects), "two projects, each with a path and a name")
        pa = next((p for p in projects if p["name"] == "proj-a"), {})
        pb = next((p for p in projects if p["name"] == "proj-b"), {})
        check("v0.1.0" in str(pa.get("last_shipped")), "A's last shipped names the tag")
        check(len(pb.get("state", [])) == 3 and pb["state"][0] == "Line one of the state.", "B's state has the first three lines")
        check(pb.get("rules_file") is True and pa.get("rules_file") is False, "the rules file is found for B and not for A")
        waits = data["waits_for_you"]
        check(len(waits) == 2 and all(w.get("command") and w.get("project") == "proj-a" for w in waits),
              "two things wait for you, both A's, each with a command")
        check(any("answer ship-a q1" in w["command"] for w in waits) and any("crew.py" in w["command"] for w in waits),
              "the commands answer the outcome question and the crew question")
        check([p["name"] for p in projects] == ["proj-a", "proj-b"], "the project with something waiting sorts first")
        check(any("Tidy the readme" in str(r) for r in pa.get("running", [])), "A's running crew job is listed")
        check(any("Second" in str(r) for r in pb.get("running", [])), "B's doing task is listed as running")
        check(set(data) >= {"generated", "waits_for_you", "projects", "gone", "usage"}, "the JSON has the documented keys")

        text = status()
        check(text.startswith("Waits for you"), "the text starts with Waits for you")
        check(text.index("proj-a") < text.index("proj-b", text.index("proj-a") + 1) and "v0.1.0" in text and "Line one of the state." in text,
              "the text shows A's block before B's, with the tag and the first state line")
        check(all(len(line) <= 60 or "/" in line for line in text.splitlines()), "lines wrap at 60 characters (paths and commands excepted)")
        only = json.loads(status("--project", b, "--json"))
        check(len(only["projects"]) == 1 and only["projects"][0]["name"] == "proj-b", "--project restricts to one project")

        run(OUTCOME, "new", "Ghost", "--done", "x", "--slug", "ghost", "--cwd", os.path.join(work, "no-such-folder"))
        data = json.loads(status("--json"))
        check(len(data["projects"]) == 2 and any("no-such-folder" in g["path"] for g in data["gone"]), "a missing folder is listed under gone, not projects")
        check("Gone" in status() and "no-such-folder" in status(), "the text has a Gone block")

        out = status("--render")
        md = os.path.join(home, "outbox", __import__("datetime").date.today().isoformat(), "status.md")
        check(os.path.exists(md), "--render writes status.md in the outbox")
        body = open(md).read() if os.path.exists(md) else ""
        check(body.startswith("# Waits for you") and "# proj-a" in body, "status.md has one heading per block")
        if "Could not" in out or "install Google Chrome" in out:
            print("SKIPPED  the PDF and phone PNG need Google Chrome or Chromium (set MSTACK_CHROME)")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("every status test passed" if not failures else "FAILED: %d" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
