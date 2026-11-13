#!/usr/bin/env python3
"""Critique checks (meta-brief, meta, the report's critique table) and the private evaluator scoreboard (evalboard.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="mstack-home-")
os.environ["MSTACK_HOME"] = HOME   # the evaluator scoreboard writes here, never to the real home
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
BOARD = os.path.join(SCRIPTS, "evalboard.py")
sys.path.insert(0, SCRIPTS)
import critique  # noqa: E402
import eval_loop  # noqa: E402
import evalboard  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data, indent=2))


def verdict(rid, n, s1, s2):
    return {"reviewer": rid, "round": n, "overall": round((s1 + s2) / 2), "top_fixes": [], "broken": [], "journeys": [
        {"id": 1, "name": "First", "score": s1, "if_fixed": 10, "what_worked": [],
         "fixes": [{"severity": "high", "where": "Home", "problem": "The button is hidden", "fix": "Show the button"}]},
        {"id": 2, "name": "Second", "score": s2, "if_fixed": 10, "what_worked": [],
         "fixes": [{"severity": "medium", "where": "List", "problem": "Small text", "fix": "Larger text"}]}]}


def meta(rid, quality, verdicts=("confirmed", "wrong")):
    return {"reviewer": rid, "checked": [
        {"journey": 1, "where": "Home", "claim": "button hidden", "severity": "high", "verdict": verdicts[0],
         "severity_ok": True, "suggested_severity": None, "fix_quality": 2, "note": "seen on the home screen"},
        {"journey": 2, "where": "List", "claim": "small text", "severity": "medium", "verdict": verdicts[1],
         "severity_ok": False, "suggested_severity": "low", "fix_quality": 1, "note": "text is 17 points"}],
        "accuracy": 0.5, "calibration": [{"journey": 2, "their_score": 5, "your_score": 7, "why": "it works"}],
        "missed": [{"journey": 1, "severity": "medium", "problem": "no undo"}],
        "usefulness": 6, "critique_quality": quality, "summary": "Half right."}


def loop(work, *args, stdin=None):
    return subprocess.run([sys.executable, LOOP] + list(args) + ["--dir", work], capture_output=True, text=True, input=stdin)


class Critique(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="mstack-critique-", dir=eval_loop.tmp_base())
        cfg = {"name": "Critique test", "about": "A test product.", "persona": "a first-time user.",
               "target": {"url": "http://127.0.0.1:{port}/"},
               "journeys": [{"id": 1, "name": "First", "task": "Do it."}, {"id": 2, "name": "Second", "task": "Do more."}],
               "reviewers": [{"id": "a", "name": "Alpha", "kind": "agent", "maker": "Maker A"},
                             {"id": "b", "name": "Beta", "kind": "agent", "maker": "Maker B"}], "views": []}
        write(os.path.join(self.work, "mstack-eval.json"), cfg)
        evalboard.save([])
        self.assertEqual(loop(self.work, "start-round").returncode, 0)

    def save_verdict(self, rid, s1, s2, n=1):
        r = loop(self.work, "verdict", "--reviewer", rid, "--json", "-", stdin=json.dumps(verdict(rid, n, s1, s2)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_meta_brief_waits_for_verdict_and_is_generic(self):
        r = json.loads(loop(self.work, "meta-brief", "--json").stdout)
        self.assertEqual(r["briefs"], [])
        self.assertEqual(r["waiting_for_verdicts"], ["a", "b"])
        self.save_verdict("a", 6, 5)
        r = json.loads(loop(self.work, "meta-brief", "--json").stdout)
        self.assertEqual(r["waiting_for_verdicts"], ["b"])
        self.assertEqual(r["checker"], "Claude Opus 5.5")
        text = read(r["briefs"][0])
        self.assertIn("Critique test", text)
        self.assertIn(os.path.join("rounds", "r1", "verdicts", "a.json"), text)
        self.assertIn(os.path.join("rounds", "r1", "meta", "a.json"), text)
        self.assertIn("--mute-audio", text)
        self.assertNotIn("{", text.split("## Reply format")[0])   # every placeholder filled in
        # the checker's brief is not a reviewer's brief
        self.assertEqual(eval_loop.readiness.brief_reviewers_dropped(eval_loop.Project(self.work), 1), [])

    def test_meta_checks_and_saves(self):
        self.save_verdict("a", 6, 5)
        bad = meta("a", 7)
        bad["checked"][0]["verdict"] = "maybe"
        bad["critique_quality"] = 12
        r = loop(self.work, "meta", "--reviewer", "a", "--json", "-", stdin=json.dumps(bad))
        self.assertEqual(r.returncode, 1)
        probs = " ".join(json.loads(r.stdout)["problems"])
        self.assertIn("verdict must be one of", probs)
        self.assertIn("critique_quality", probs)
        r = loop(self.work, "meta", "--reviewer", "b", "--json", "-", stdin=json.dumps(meta("b", 7)))
        self.assertEqual(r.returncode, 1)
        self.assertIn("verdict for round 1 first", r.stdout)
        # the checker wrote the file itself: meta checks it in place
        write(os.path.join(self.work, "rounds", "r1", "meta", "a.json"), meta("a", 7))
        r = loop(self.work, "meta", "--reviewer", "a", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["held"], "1 of 2")
        self.assertIn("recorded 1 reviewer", out["scoreboard"])

    def test_summary(self):
        s = critique.summary(meta("a", 7, ("partly", "not-reproduced")))
        self.assertEqual((s["checked"], s["held"], s["serious"], s["serious_held"]), (2, 1, 1, 1))
        self.assertEqual((s["severity_ok"], s["fix_quality"], s["missed"]), (0.5, 0.75, 1))

    def test_report_shows_critique_quality(self):
        self.save_verdict("a", 6, 5)
        self.save_verdict("b", 8, 8)
        write(os.path.join(self.work, "rounds", "r1", "meta", "a.json"), meta("a", 7))
        r = loop(self.work, "report", "--no-notify", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        page = read(os.path.join(self.work, "report.html"))
        self.assertIn("<h2>Critique quality</h2>", page)
        self.assertIn("Half right.", page)
        self.assertIn("Not checked this round", page)   # Beta has no check
        self.assertIn("recorded 2 reviewer", json.loads(r.stdout)["scoreboard"])

    def test_report_without_checks_has_no_section(self):
        self.save_verdict("a", 6, 5)
        self.assertEqual(loop(self.work, "report", "--no-notify").returncode, 0)
        self.assertNotIn("<h2>Critique quality</h2>", read(os.path.join(self.work, "report.html")))


class Scoreboard(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="mstack-board-", dir=eval_loop.tmp_base())
        cfg = {"name": "Secret Product", "about": "x", "persona": "y", "target": {"url": "http://127.0.0.1:{port}/"},
               "journeys": [{"id": 1, "name": "First", "task": "Do it."}, {"id": 2, "name": "Second", "task": "Do more."}],
               "reviewers": [{"id": "a", "name": "Alpha", "maker": "Maker A"}, {"id": "b", "name": "Beta", "maker": "Maker B"}],
               "views": []}
        write(os.path.join(self.work, "mstack-eval.json"), cfg)
        for n, (a, b) in ((1, (4, 6)), (2, (6, 8))):
            write(os.path.join(self.work, "rounds", "r%d" % n, "verdicts", "a.json"), verdict("a", n, a, a))
            write(os.path.join(self.work, "rounds", "r%d" % n, "verdicts", "b.json"), verdict("b", n, b, b))
        write(os.path.join(self.work, "rounds", "r2", "verdicts", "a.compare.json"), {"compare": {}})
        write(os.path.join(self.work, "rounds", "r2", "meta", "a.json"), meta("a", 8))
        write(os.path.join(self.work, "rounds", "r2", "meta", "b.json"), meta("b", 5, ("wrong", "wrong")))
        evalboard.save([])

    def run_board(self, *args):
        return subprocess.run([sys.executable, BOARD] + list(args), capture_output=True, text=True)

    def test_record_backfill_and_board(self):
        r = self.run_board("record", "--dir", self.work, "--round", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = evalboard.load()
        self.assertEqual(sorted(x["reviewer"] for x in rows), ["a", "b"])   # the comparison pass is not a reviewer
        a = next(x for x in rows if x["reviewer"] == "a")
        self.assertEqual((a["project"], a["app_score"], a["strictness"]), ("Secret Product", 6, -1))
        self.assertEqual(a["check"]["critique_quality"], 8)
        self.assertEqual(a["check"]["calibration_error"], 1)
        # recording the same round again replaces it
        self.run_board("record", "--dir", self.work, "--round", "2")
        self.assertEqual(len(evalboard.load()), 2)
        r = self.run_board("backfill", "--dir", self.work, "--project", "Renamed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([x for x in evalboard.load() if x["project"] == "Renamed"]), 4)
        r = self.run_board("board", "--json")
        out = json.loads(r.stdout)
        self.assertTrue(out["scoreboard"].startswith(os.path.join(HOME, "evals")))
        page = read(out["scoreboard"])
        self.assertLess(page.index("Alpha"), page.index("Beta"))   # ranked by critique quality
        self.assertIn("Half right.", read(evalboard.ledger_path()))

    def test_public_board_hides_names_and_notes(self):
        self.run_board("record", "--dir", self.work, "--round", "2")
        out = json.loads(self.run_board("board", "--public", "--json").stdout)
        self.assertTrue(out["scoreboard"].endswith("scoreboard-public.html"))
        page = read(out["scoreboard"])
        self.assertNotIn("Secret Product", page)
        self.assertNotIn("Half right.", page)
        self.assertIn("Project A", page)
        self.assertNotIn(self.work, page)

    def test_scoreboard_off_in_config(self):
        cfg = json.loads(read(os.path.join(self.work, "mstack-eval.json")))
        cfg["scoreboard"] = False
        write(os.path.join(self.work, "mstack-eval.json"), cfg)
        self.assertIn("off", critique.auto_record(eval_loop.Project(self.work), 2))
        self.assertEqual(evalboard.load(), [])

    def test_ledger_never_inside_a_repository(self):
        repo = tempfile.mkdtemp(prefix="mstack-repo-", dir=eval_loop.tmp_base())
        os.makedirs(os.path.join(repo, ".git"))
        env = dict(os.environ, MSTACK_HOME=os.path.join(repo, ".mstack"))
        r = subprocess.run([sys.executable, BOARD, "record", "--dir", self.work, "--round", "1"], capture_output=True,
                           text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("inside the git repository", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(repo, ".mstack")))
        # and the loop carries on: a scoreboard problem never fails a verdict
        os.environ["MSTACK_HOME"] = os.path.join(repo, ".mstack")
        try:
            self.assertIn("not recorded", critique.auto_record(eval_loop.Project(self.work), 1))
        finally:
            os.environ["MSTACK_HOME"] = HOME


if __name__ == "__main__":
    unittest.main()
