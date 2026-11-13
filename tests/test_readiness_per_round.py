#!/usr/bin/env python3
"""Per-round reviewers: readiness and report respect who had briefs each round, not today's config alone."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MSTACK_HOME"] = __import__("tempfile").mkdtemp(prefix="mstack-home-")   # the evaluator scoreboard writes here, never to the real home
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
sys.path.insert(0, SCRIPTS)
import eval_loop  # noqa: E402
import readiness  # noqa: E402
import report  # noqa: E402


def verdict(rid, n, score=9):
    return {
        "reviewer": rid,
        "round": n,
        "overall": score,
        "top_fixes": [],
        "broken": [],
        "journeys": [
            {"id": 1, "name": "One journey", "score": score, "if_fixed": 10, "what_worked": [], "fixes": []},
        ],
    }


def write_review(root, reviewers, rounds_data):
    os.makedirs(root, exist_ok=True)
    cfg = {
        "name": "Per-round reviewers test",
        "journeys": [{"id": 1, "name": "One journey", "task": "Do the thing."}],
        "reviewers": reviewers,
        "views": [],
    }
    with open(os.path.join(root, "mstack-eval.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    for n, rids in rounds_data.items():
        base = os.path.join(root, "rounds", "r%d" % n)
        os.makedirs(os.path.join(base, "briefs"), exist_ok=True)
        os.makedirs(os.path.join(base, "verdicts"), exist_ok=True)
        for rid in rids:
            with open(os.path.join(base, "briefs", "%s.md" % rid), "w", encoding="utf-8") as fh:
                fh.write("# brief\n")
            with open(os.path.join(base, "verdicts", "%s.json" % rid), "w", encoding="utf-8") as fh:
                json.dump(verdict(rid, n), fh)


class PerRoundReviewers(unittest.TestCase):
    def test_late_joiner_not_missing_from_earlier_rounds(self):
        work = tempfile.mkdtemp(prefix="mstack-readiness-", dir=eval_loop.tmp_base())
        try:
            a, b, c = "rev-a", "rev-b", "rev-c"
            r12 = [a, b]
            reviewers_ab = [
                {"id": a, "name": "Reviewer A", "kind": "agent"},
                {"id": b, "name": "Reviewer B", "kind": "agent"},
            ]
            write_review(work, reviewers_ab, {1: r12, 2: r12})

            with open(os.path.join(work, "mstack-eval.json"), "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg["reviewers"].append({"id": c, "name": "Reviewer C", "kind": "agent"})
            with open(os.path.join(work, "mstack-eval.json"), "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)

            write_review(work, cfg["reviewers"], {3: [a, b, c]})
            base3 = os.path.join(work, "rounds", "r3")
            os.remove(os.path.join(base3, "verdicts", "%s.json" % c))

            p = eval_loop.Project(work)

            for n in (1, 2):
                st = readiness.round_state(p, n)
                self.assertEqual(st["missing_verdicts"], [], "round %d" % n)
                self.assertFalse(any("no verdict yet" in r for r in st["not_ready_because"]), "round %d" % n)

            st3 = readiness.round_state(p, 3)
            self.assertEqual(st3["reviewers"], [a, b, c])
            self.assertEqual(st3["joined"], [c])
            self.assertEqual(st3["missing_verdicts"], [c])

            nxt = readiness.next_step(p)
            self.assertIn(c, nxt)
            self.assertIn("verdict", nxt.lower())

            path, _summary = report.build(p)
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
            self.assertIn("joined at round 3", html)
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
