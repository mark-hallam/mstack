#!/usr/bin/env python3
"""Re-grade of last round's fixes, the blocker severity, personas per journey and "could not test"."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
sys.path.insert(0, SCRIPTS)
import eval_loop  # noqa: E402
import readiness  # noqa: E402
import report  # noqa: E402
import verdicts  # noqa: E402

BIG = "Make the button bigger"
SEEN = "The Add book button now reads Add book and is 44 points tall"


def fix(sev, where, text):
    return {"severity": sev, "where": where, "problem": "Problem with " + where, "fix": text}


def verdict(rid, n, j1, j2, fixes1=(), fixes2=(), **extra):
    v = {"reviewer": rid, "round": n, "overall": 6, "top_fixes": [], "broken": [], "journeys": [
        {"id": 1, "name": "First", "score": j1, "if_fixed": 10, "what_worked": [], "fixes": list(fixes1)},
        {"id": 2, "name": "Second", "score": j2, "if_fixed": 10, "what_worked": [], "fixes": list(fixes2)}]}
    v.update(extra)
    return v


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh, indent=2)


def loop(work, *args, stdin=None):
    return subprocess.run([sys.executable, LOOP] + list(args) + ["--dir", work], capture_output=True, text=True, input=stdin)


class Regrade(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="mstack-regrade-", dir=eval_loop.tmp_base())
        self.cfg = {
            "name": "Regrade test", "about": "A test product.", "persona": "a first-time user.",
            "personas": [{"id": "child", "who": "a seven year old who reads short words"}],
            "journeys": [{"id": 1, "name": "First", "task": "Do the first thing.", "persona": "child"},
                         {"id": 2, "name": "Second", "task": "Do the second thing."}],
            "reviewers": [{"id": "a", "name": "A", "kind": "agent"}, {"id": "b", "name": "B", "kind": "agent"}],
            "views": []}
        write(os.path.join(self.work, "mstack-eval.json"), self.cfg)
        for n in (1, 2):
            write(os.path.join(self.work, "rounds", "r%d" % n, "shots", "home.png"), "x")
            write(os.path.join(self.work, "rounds", "r%d" % n, "changes.md"), "- a change\n")
        r1 = os.path.join(self.work, "rounds", "r1", "verdicts")
        write(os.path.join(r1, "a.json"), verdict("a", 1, 5, 6, [fix("high", "Home", BIG)], [fix("medium", "Tabs", "Rename the tab")]))
        write(os.path.join(r1, "b.json"), verdict("b", 1, 6, 6, [fix("high", "Home", BIG)], [fix("low", "Back", "Add a back link")]))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def project(self):
        return eval_loop.Project(self.work)

    def test_regrade_flow(self):
        r = loop(self.work, "brief", "--round", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cb = open(os.path.join(self.work, "rounds", "r2", "briefs", "a-compare.md"), encoding="utf-8").read()
        for needle in ("f1", "f2", "f3", BIG, "Rename the tab", "Add a back link", '"regrade"'):
            self.assertIn(needle, cb)
        self.assertEqual(cb.count(BIG), 1, "fixes are de-duplicated by text")
        save = lambda rid, v: loop(self.work, "verdict", "--round", "2", "--reviewer", rid, "-", stdin=json.dumps(v))  # noqa: E731
        self.assertEqual(save("a", verdict("a", 2, 7, 7)).returncode, 0)
        self.assertEqual(save("b", verdict("b", 2, 8, 8)).returncode, 0)

        def cmp_(rid, states):
            body = {"compare": {"improved": ["x"], "regressed": [], "unchanged": []},
                    "regrade": [{"id": i, "state": s, "seen": SEEN} for i, s in states]}
            return loop(self.work, "verdict", "--round", "2", "--reviewer", rid, "--compare", "-", stdin=json.dumps(body))

        bad = cmp_("a", [("f1", "done"), ("f2", "partly")])
        self.assertEqual(bad.returncode, 1)
        self.assertIn("f3", bad.stdout + bad.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.work, "rounds", "r2", "verdicts", "a.compare.json")))
        wrong = cmp_("a", [("f1", "done"), ("f2", "partly"), ("f3", "maybe")])
        self.assertEqual(wrong.returncode, 1)
        self.assertEqual(cmp_("a", [("f1", "done"), ("f2", "partly"), ("f3", "not")]).returncode, 0)
        self.assertEqual(cmp_("b", [("f1", "done"), ("f2", "done"), ("f3", "not_testable")]).returncode, 0)
        path, _ = report.build(self.project())
        page = open(path, encoding="utf-8").read()
        self.assertIn("partly", page)
        self.assertIn("1 partly", page)
        self.assertIn(SEEN, page)
        self.assertIn(BIG, page)

    def test_blocker(self):
        p = self.project()
        blocker = fix("blocker", "Pay", "Let the person pay")
        bad = verdicts.check_verdict(p, verdict("a", 3, 8, 6, [blocker]))
        self.assertTrue(any("blocker" in x for x in bad), bad)
        self.assertEqual(verdicts.check_verdict(p, verdict("a", 3, 4, 6, [blocker])), [])
        r3 = os.path.join(self.work, "rounds", "r3", "verdicts")
        write(os.path.join(r3, "a.json"), verdict("a", 3, 4, 9, [blocker, fix("high", "Home", BIG)]))
        write(os.path.join(r3, "b.json"), verdict("b", 3, 9, 9, [fix("high", "Home", BIG)]))
        p = self.project()
        chk = readiness.round_check(p, 3)
        self.assertFalse(chk["ready"])
        self.assertTrue(any("1 blocker" in x for x in chk["reasons"]), chk["reasons"])
        self.assertEqual(readiness.do_next(p, 3)[0]["severity"], "blocker")

    def test_personas(self):
        r = loop(self.work, "brief", "--round", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sb = open(os.path.join(self.work, "rounds", "r2", "briefs", "a.md"), encoding="utf-8").read()
        self.assertIn("Play this person: a seven year old who reads short words", sb)
        self.assertEqual(sb.count("Play this person"), 1)
        self.cfg["journeys"][1]["persona"] = "sibling"
        write(os.path.join(self.work, "mstack-eval.json"), self.cfg)
        r = loop(self.work, "brief", "--round", "2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("sibling", r.stdout + r.stderr)

    def test_could_not_test(self):
        p = self.project()
        v = verdict("a", 3, 7, 7, could_not_test=["Payments: needs a real card"], did_not_touch=["Deleting the account"])
        self.assertEqual(verdicts.check_verdict(p, v), [])
        self.assertTrue(verdicts.check_verdict(p, dict(v, could_not_test="nope")))
        write(os.path.join(self.work, "rounds", "r3", "verdicts", "a.json"), v)
        page = open(report.build(self.project())[0], encoding="utf-8").read()
        self.assertIn("Payments: needs a real card", page)
        self.assertIn("Deleting the account", page)


if __name__ == "__main__":
    unittest.main()
