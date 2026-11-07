#!/usr/bin/env python3
"""Self-test for the question budget in outcome-first: the cap, the defaults line, and the one-word reply.

Runs in a throwaway MSTACK_HOME.

  python3 tests/test_outcome_budget.py
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
    work = tempfile.mkdtemp(prefix="mstack-budget-test-")
    env = dict(os.environ, MSTACK_HOME=os.path.join(work, "home"))

    def run(*args):
        r = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  outcome.py %s exited %d" % (" ".join(args), r.returncode))
        return r.stdout

    def js(*args):
        return json.loads(run(*(list(args) + ["--json"])))

    try:
        run("new", "Budget", "--slug", "b", "--done", "it is done")
        for i in range(1, 10):
            if i in (2, 8):
                run("ask", "b", "Question %d" % i)
            else:
                run("ask", "b", "Question %d" % i, "--default", "d%d" % i)
        data = js("questions", "b")
        ids = [q["id"] for q in data["ask"]]
        check(data["cap"] == 6 and len(ids) == 6, "default cap is 6 and six questions are asked")
        check(ids[:2] == ["q2", "q8"], "questions without a default come first")
        check(len(data["by_default"]) == 3, "three questions are taken by default")
        text = run("questions", "b")
        check("Taken by default unless you say otherwise:" in text and "(default: d9)" in text, "text output lists the defaults")
        with open(os.path.join(work, "home", "config.json"), "w") as fh:
            json.dump({"max_questions": 3}, fh)
        data = js("questions", "b")
        ids = [q["id"] for q in data["ask"]]
        check(data["cap"] == 3 and len(ids) == 3 and ids[:2] == ["q2", "q8"], "a cap of 3 asks three, two of them undefaulted")
        with open(os.path.join(work, "home", "config.json"), "w") as fh:
            json.dump({"max_questions": 1}, fh)
        data = js("questions", "b")
        check(len(data["ask"]) == 2 and "more than the cap" in run("questions", "b"),
              "undefaulted questions may exceed the cap, and the output says so")
        run("answer", "b", "Use The Defaults")
        o = json.load(open(os.path.join(work, "home", "outcomes", "b", "outcome.json")))
        qs = {q["id"]: q for q in o["questions"]}
        check(all(qs["q%d" % i]["answer"] is not None for i in (1, 3, 4, 5, 6, 7, 9)), "every question with a default is answered")
        check(qs["q2"]["answer"] is None and qs["q8"]["answer"] is None, "questions without a default stay open")
        prog = open(os.path.join(work, "home", "outcomes", "b", "progress.md")).read()
        check("(taken by default)" in prog and "Answer: d9 (taken by default)" in prog, "progress file says taken by default")
        check("the person chose the defaults" in o["log"][-1]["text"].lower(), "log says the person chose the defaults")
        run("answer", "b", "q9", "no, do it the other way")
        o = json.load(open(os.path.join(work, "home", "outcomes", "b", "outcome.json")))
        q9 = [q for q in o["questions"] if q["id"] == "q9"][0]
        check(q9["answer"] == "no, do it the other way" and "q9 answered" in o["log"][-1]["text"], "a defaulted question can still be answered")
        prog = open(os.path.join(work, "home", "outcomes", "b", "progress.md")).read()
        check("Answer: no, do it the other way" in prog, "the replacement shows in the progress file")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("every outcome budget check passed" if not failures else "FAILED: %d" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
