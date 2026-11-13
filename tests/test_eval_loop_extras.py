#!/usr/bin/env python3
"""Maker, model, {home} placeholder and enabled reviewers for the multi-evaluator loop."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MSTACK_HOME"] = __import__("tempfile").mkdtemp(prefix="mstack-home-")   # the evaluator scoreboard writes here, never to the real home
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


TEMPLATE = os.path.join(ROOT, "skills", "multi-evaluator", "templates", "mstack-eval.json")


class StarterTemplate(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding="utf-8") as fh:
            self.text = fh.read()
        self.cfg = json.loads(self.text)

    def test_neutral(self):
        for word in ("Apple", "iPhone", "macOS", "iOS", "Mac "):
            self.assertNotIn(word, self.text)
        self.assertIn("first-time user", self.cfg["persona"])
        familiar = [c for c in self.cfg["criteria"] if c["name"] == "Familiar"][0]
        self.assertIn("conventions of the platform", familiar["means"])
        self.assertEqual([c["name"] for c in self.cfg["criteria"]],
                         ["Clear", "Quick", "Trust", "Familiar", "Calm", "Works everywhere"])

    def test_cursor_entry_is_portable_and_off(self):
        ids = [r["id"] for r in self.cfg["reviewers"]]
        self.assertIn("cursor", ids)
        self.assertNotIn("cursor-grok", ids)
        r = [x for x in self.cfg["reviewers"] if x["id"] == "cursor"][0]
        self.assertIs(r["enabled"], False)
        self.assertEqual(r["command"][0], "cursor-agent")           # a program name found on PATH, no fixed folder
        self.assertNotIn("{home}", json.dumps(r))
        self.assertNotIn("--model", r["command"])
        self.assertEqual(r.get("model"), "")
        self.assertNotIn("grok", json.dumps(r).lower())

    def test_reference_explains_each_flag(self):
        with open(os.path.join(ROOT, "skills", "multi-evaluator", "references", "config.md"), encoding="utf-8") as fh:
            ref = fh.read()
        for flag in ("`-p`", "`--trust`", "`-f`", "`--output-format text`", "`--workspace {work}`", '"--model"'):
            self.assertIn(flag, ref)


class CommandReviewers(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="mstack-cmdrev-", dir=eval_loop.tmp_base())
        self.env = dict(os.environ, HOME=self.work, MSTACK_HOME=os.path.join(self.work, ".mstack"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.work, ignore_errors=True)

    def make(self, reviewer):
        import subprocess
        cfg = {"name": "Cmd test", "journeys": [{"id": 1, "name": "One", "task": "Do it."}],
               "views": [{"id": "v", "name": "V", "steps": [{"do": "goto", "url": "http://127.0.0.1/"}]}],
               "reviewers": [reviewer]}
        with open(os.path.join(self.work, "mstack-eval.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        rnd = os.path.join(self.work, "rounds", "r1")
        os.makedirs(os.path.join(rnd, "shots"), exist_ok=True)
        with open(os.path.join(rnd, "shots", "v.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(rnd, "criteria.json"), "w", encoding="utf-8") as fh:
            json.dump([], fh)
        r = subprocess.run([sys.executable, LOOP, "brief", "--dir", self.work, "--round", "1"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def review(self):
        import subprocess
        r = subprocess.run([sys.executable, LOOP, "review", "--dir", self.work, "--round", "1", "--json"],
                           capture_output=True, text=True, env=self.env, timeout=60)
        return r.returncode, json.loads(r.stdout)

    def test_missing_program_is_named(self):
        self.make({"id": "cursor", "name": "Cursor agent", "kind": "command",
                   "command": ["no-such-reviewer-program-xyz", "-p"]})
        code, data = self.review()
        self.assertEqual(code, 1)
        problem = data["results"]["cursor"]["problem"]
        self.assertIn("no-such-reviewer-program-xyz", problem)
        self.assertIn("not found", problem)
        self.assertIn('"command"', problem)
        self.assertIn("mstack-eval.json", problem)

    def test_old_cursor_grok_entry_still_reads(self):
        import verdicts
        # a stand-in program that only prints a line: no real reviewer is started
        self.make({"id": "cursor-grok", "name": "Grok via Cursor", "maker": "xAI", "model": "grok-4.7-medium",
                   "kind": "command", "command": [sys.executable, "-c", "print('no verdict here')"]})
        p = eval_loop.Project(self.work)
        self.assertEqual([r["id"] for r in p.enabled_reviewers()], ["cursor-grok"])
        self.assertTrue(os.path.exists(os.path.join(self.work, "rounds", "r1", "briefs", "cursor-grok.md")))
        self.assertEqual(verdicts.reviewer_model(p.reviewer("cursor-grok")), "grok-4.7-medium")
        code, data = self.review()
        self.assertNotIn("was not found", json.dumps(data))
        self.assertIn("did not fit the format", data["results"]["cursor-grok"]["problem"])


if __name__ == "__main__":
    unittest.main()
