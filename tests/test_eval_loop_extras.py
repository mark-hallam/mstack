#!/usr/bin/env python3
"""Maker, model, {home} placeholder and enabled reviewers for the multi-evaluator loop."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
sys.path.insert(0, SCRIPTS)
import eval_loop  # noqa: E402
import readiness  # noqa: E402


class FillHome(unittest.TestCase):
    def test_home_placeholder(self):
        home = os.path.expanduser("~")
        out = eval_loop.fill("{home}/.local/bin/agent", {"home": home})
        self.assertEqual(out, os.path.join(home, ".local/bin/agent"))


class EnabledReviewers(unittest.TestCase):
    def test_disabled_reviewer_skipped(self):
        work = tempfile.mkdtemp(prefix="mstack-enabled-", dir=eval_loop.tmp_base())
        try:
            cfg = {
                "name": "Enabled test",
                "journeys": [{"id": 1, "name": "One", "task": "Do it."}],
                "views": [{"id": "v", "name": "V", "steps": [{"do": "goto", "url": "http://127.0.0.1/"}]}],
                "reviewers": [
                    {"id": "on", "name": "On", "kind": "agent"},
                    {"id": "off", "name": "Off", "kind": "agent", "enabled": False},
                ],
            }
            os.makedirs(work, exist_ok=True)
            with open(os.path.join(work, "mstack-eval.json"), "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            rnd = os.path.join(work, "rounds", "r1")
            os.makedirs(os.path.join(rnd, "shots"), exist_ok=True)
            with open(os.path.join(rnd, "changes.md"), "w", encoding="utf-8") as fh:
                fh.write("# Round 1\n")
            with open(os.path.join(rnd, "criteria.json"), "w", encoding="utf-8") as fh:
                json.dump([], fh)
            with open(os.path.join(rnd, "views.json"), "w", encoding="utf-8") as fh:
                json.dump({"views": cfg["views"], "build": None}, fh)
            with open(os.path.join(rnd, "shots", "v.png"), "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n")
            import subprocess
            r = subprocess.run(
                [sys.executable, LOOP, "brief", "--dir", work, "--round", "1"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(os.path.join(rnd, "briefs", "on.md")))
            self.assertFalse(os.path.exists(os.path.join(rnd, "briefs", "off.md")))
            p = eval_loop.Project(work)
            self.assertEqual(readiness.round_reviewers(p, 1), ["on"])
            st = readiness.round_state(p, 1)
            self.assertEqual(st["reviewers"], ["on"])
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
