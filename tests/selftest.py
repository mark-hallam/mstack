#!/usr/bin/env python3
"""Self-test for the multi-evaluator skill: three rounds on a tiny local page, no AI, no network beyond localhost.

Round N reviews examples/sample-app/round-N, a tiny page that gets better each round. Each round
captures the fixed screens, writes the briefs, runs a command line stand-in reviewer (which starts its own
copy of the page with the brief's serve command and drives it with the journey driver), saves a second
stand-in's verdict through the agent path (verdict), and builds the report. Then it checks the report
has the trend, the journey table, before and after images and the filmstrip, and that bad verdicts are
refused.

  python3 tests/selftest.py [--keep] [--write-example]

--write-example also copies the finished report to examples/sample-report.html.
Needs Node.js 18 or later and Google Chrome or Chromium. Exits 0 when every check passes.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
STAND_IN = os.path.join(ROOT, "tests", "stand_in_reviewer.py")
STATIC = os.path.join(ROOT, "tests", "static_server.py")
SAMPLE = os.path.join(ROOT, "examples", "sample-app")
sys.path.insert(0, SCRIPTS)
import eval_loop  # noqa: E402

failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def run(review, *args, expect=0, stdin=None):
    r = subprocess.run([sys.executable, LOOP] + list(args) + ["--dir", review], capture_output=True, text=True,
                       input=stdin, timeout=600)
    if r.returncode != expect:
        print(r.stdout, r.stderr)
        raise SystemExit("FAIL  %s exited %d, expected %d" % (" ".join(args), r.returncode, expect))
    return r.stdout


def config(site):
    return {
        "name": "Sample reading list",
        "about": "A one page reading list. People add books and mark them as read. Apple clean, light theme first.",
        "persona": "a first-time user who is not technical.",
        "note": "Illustrative: the scores come from the self-test's stand-in reviewers, not from a real AI review.",
        "target": {"url": "http://127.0.0.1:{port}/", "start": [sys.executable, STATIC, "{port}", site], "cwd": site},
        "views": [
            {"id": "home-desktop", "name": "Home", "group": "Desktop", "viewport": "desktop",
             "steps": [{"do": "goto", "url": "{url}", "ms": 600}]},
            {"id": "home-phone", "name": "Home", "group": "Phone", "viewport": "phone",
             "steps": [{"do": "goto", "url": "{url}", "ms": 600}]},
            {"id": "home-dark", "name": "Home", "group": "Dark theme", "viewport": "desktop", "scheme": "dark",
             "steps": [{"do": "goto", "url": "{url}", "ms": 600}]}],
        "journeys": [{"id": 1, "name": "Add a book", "task": "Add a book to the list."},
                     {"id": 2, "name": "Mark one as read", "task": "Mark a book as read and see the count change."}],
        "criteria": [{"name": "Clear", "means": "obvious what to do next."},
                     {"name": "Calm", "means": "nothing shouting."}],
        "stages": [{"name": "Stage 1", "from_round": 3, "criteria": [{"name": "Copy", "means": "plain English."}]}],
        "reviewers": [
            {"id": "stand-in", "name": "Stand-in A", "kind": "command", "colour": "#C15F3C",
             "command": [sys.executable, STAND_IN, "--id", "stand-in", "--round", "{round}", "--work", "{work}"]},
            {"id": "second", "name": "Stand-in B", "kind": "agent", "colour": "#1f6feb"}],
    }


CHANGES = {
    1: "- The starting point: nothing changed yet.",
    2: "- Plain words on every button (Mark as read, Add a book) instead of codes.\n- The system font, a clear title and calm colours.",
    3: "- The list sits on a card with a short summary line.\n- A dark theme and visible keyboard focus.\n- Screen reader labels on every button.",
}


def agent_verdict(n):
    score = {1: 5, 2: 8, 3: 10}[n]
    return json.dumps({"reviewer": "second", "round": n, "overall": score, "top_fixes": [], "broken": [],
                       "journeys": [{"id": j, "name": "J%d" % j, "score": score, "if_fixed": 10, "what_worked": [],
                                     "fixes": []} for j in (1, 2)]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--write-example", action="store_true")
    args = ap.parse_args()
    if not shutil.which("node") or not eval_loop.find_chrome():
        print("SKIPPED: the self-test needs Node.js 18 or later and Google Chrome or Chromium (set MSTACK_CHROME).")
        sys.exit(77)
    work = tempfile.mkdtemp(prefix="mstack-selftest-", dir=eval_loop.tmp_base())
    review = os.path.join(work, "review")
    os.makedirs(review)
    try:
        run(review, "init", "--name", "Throwaway")
        check(os.path.exists(os.path.join(review, "mstack-eval.json")), "init writes a starter config")
        for n in (1, 2, 3):
            site = os.path.join(SAMPLE, "round-%d" % n)
            with open(os.path.join(review, "mstack-eval.json"), "w") as fh:
                json.dump(config(site), fh, indent=2)
            run(review, "start-round")
            with open(os.path.join(review, "rounds", "r%d" % n, "changes.md"), "w") as fh:
                fh.write("# Round %d\n\n%s\n" % (n, CHANGES[n]))
            out = run(review, "capture", "--json")
            views = json.loads(out)["views"]
            check(len(views) == 3 and all(v["ok"] for v in views), "round %d: three fixed screens captured" % n)
            run(review, "brief")
            brief = open(os.path.join(review, "rounds", "r%d" % n, "briefs", "stand-in.md")).read()
            check("serve --dir" in brief and "drive.mjs" in brief and "Reply format" in brief,
                  "round %d: the brief has set up, driver and reply format" % n)
            check(("Copy" in brief) == (n >= 3), "round %d: the criteria grow from round 3" % n)
            if n > 1:
                check("r%d/shots" % (n - 1) in brief, "round %d: the brief points at last round's screens" % n)
            status = json.loads(run(review, "status", "--json"))
            check("review" in status["next"], "round %d: status says to run the reviewers" % n)
            run(review, "review", "--only", "stand-in")
            run(review, "verdict", "--reviewer", "second", "-", stdin=agent_verdict(n))
            check(sorted(os.listdir(os.path.join(review, "rounds", "r%d" % n, "verdicts"))) == ["second.json", "stand-in.json"],
                  "round %d: both verdicts saved" % n)
            run(review, "report", "--no-notify")
        shots = lambda n: open(os.path.join(review, "rounds", "r%d" % n, "shots", "home-desktop.png"), "rb").read()  # noqa: E731
        check(shots(1) != shots(2) != shots(3), "each round's screenshots differ")
        page = open(os.path.join(review, "report.html"), encoding="utf-8").read()
        check("<svg" in page and "Target 10" in page, "the report has the score trend")
        check("Stand-in A" in page and "Stand-in B" in page, "the report names both reviewers")
        check("Before (round 2)" in page and "After (round 3)" in page, "the report has before and after captions")
        check(len(re.findall(r"src='data:image/jpeg;base64,", page)) >= 6 + 9, "the report embeds before, after and filmstrip images")
        check("Every round" in page, "the report has the filmstrip")
        check("if fixed" in page and "Add a book" in page, "the report has each journey with its if fixed score")
        check("The criteria each round used" in page and "chip new" in page, "the report shows the criteria grew")
        check("src='http" not in page and "<link" not in page, "the report is self-contained")
        status = json.loads(run(review, "status", "--json"))
        check(status["next"].startswith("this round passes the stopping rule"), "status says round 3 passes the stopping rule and must hold")
        r2, r3 = status["rounds"][1], status["rounds"][2]
        check(not r2["ready"] and any("below 9" in x for x in r2["not_ready_because"]) and r3["ready"],
              "round 2 fails the stopping rule (below 9) and round 3 passes it")
        check("Not ready for people" not in page and "passes the stopping rule" in page, "the report shows the stopping rule state")
        ten_with_fix = json.dumps({"reviewer": "second", "round": 3, "overall": 10, "journeys": [
            {"id": 1, "score": 10, "if_fixed": 10, "fixes": [{"severity": "low", "fix": "x"}]}, {"id": 2, "score": 8, "if_fixed": 7}]})
        probs = json.loads(run(review, "validate", "-", "--json", expect=1, stdin=ten_with_fix))["problems"]
        check(any("a 10 means nothing is left" in x for x in probs) and any("cannot be below the score" in x for x in probs),
              "validate refuses a 10 with fixes and an if_fixed below the score")
        check(status["rounds"][-1]["overall"] == {"second": 10, "stand-in": 9}, "status reports the latest scores")
        bad = json.dumps({"reviewer": "second", "round": 3, "overall": 11, "journeys": [{"id": 1, "score": 5}]})
        out = run(review, "validate", "-", "--json", expect=1, stdin=bad)
        probs = json.loads(out)["problems"]
        check(any("overall" in x for x in probs) and any("not scored: 2" in x for x in probs)
              and any("if_fixed" in x for x in probs), "validate refuses a bad verdict and says why")
        run(review, "verdict", "--reviewer", "nobody", "-", expect=1, stdin=agent_verdict(3))
        check(True, "verdict refuses an unknown reviewer")
        check(eval_loop.port_free(8900), "nothing is left running on the reviewer's port")
        if args.write_example:
            dest = os.path.join(ROOT, "examples", "sample-report.html")
            shutil.copyfile(os.path.join(review, "report.html"), dest)
            print("wrote " + dest)
    finally:
        if args.keep:
            print("kept " + work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
