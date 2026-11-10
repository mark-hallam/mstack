#!/usr/bin/env python3
"""Build at capture: git commit in views.json, report labels, status JSON."""
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
import report  # noqa: E402


def git(*args, cwd):
    # a stand-in author, so a commit works on a computer where git has no name set
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost"] + list(args), cwd=cwd,
                          capture_output=True, text=True, check=True)


class CaptureBuildTest(unittest.TestCase):
    def setUp(self):
        self.product = tempfile.mkdtemp(prefix="mstack-product-git-")
        git("init", "-q", cwd=self.product)
        with open(os.path.join(self.product, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><title>test</title><p>one</p>")
        git("add", "index.html", cwd=self.product)
        git("commit", "-q", "-m", "first", cwd=self.product)
        self.commit1 = git("rev-parse", "HEAD", cwd=self.product).stdout.strip()
        with open(os.path.join(self.product, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><title>test</title><p>two</p>")
        git("add", "index.html", cwd=self.product)
        git("commit", "-q", "-m", "second", cwd=self.product)
        self.commit2 = git("rev-parse", "HEAD", cwd=self.product).stdout.strip()

        self.review = tempfile.mkdtemp(prefix="mstack-review-build-")
        os.makedirs(os.path.join(self.review, "rounds"))
        cfg = {
            "name": "Build recording test",
            "about": "Tiny page.",
            "journeys": [{"id": 1, "name": "Look", "task": "Open the page."}],
            "criteria": [{"name": "Clear", "means": "obvious."}],
            "target": {"url": "http://127.0.0.1:{port}/", "cwd": self.product},
            "views": [
                {"id": "home", "name": "Home", "viewport": {"w": 400, "h": 300},
                 "steps": [{"do": "goto", "url": "{url}", "ms": 100}]},
            ],
            "reviewers": [{"id": "a", "name": "Reviewer A", "kind": "agent"}],
        }
        with open(os.path.join(self.review, "mstack-eval.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)

    def tearDown(self):
        shutil.rmtree(self.product, ignore_errors=True)
        shutil.rmtree(self.review, ignore_errors=True)

    def round_dir(self, n):
        return os.path.join(self.review, "rounds", "r%d" % n)

    def write_round_views(self, n, commit, dirty=False, changes="- First capture."):
        base = self.round_dir(n)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "views.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "views": [{"id": "home", "name": "Home", "viewport": {"w": 400, "h": 300}}],
                "build": {"commit": commit, "dirty": dirty, "captured": "2026-11-07T04:30:00+00:00"},
            }, fh, indent=2)
        with open(os.path.join(base, "changes.md"), "w", encoding="utf-8") as fh:
            fh.write("# Round %d\n\n%s\n" % (n, changes))
        os.makedirs(os.path.join(base, "shots"), exist_ok=True)
        with open(os.path.join(base, "shots", "home.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")

    def test_product_build_matches_head(self):
        b = eval_loop.product_build(self.product)
        self.assertEqual(b["commit"], self.commit2)
        self.assertFalse(b["dirty"])
        self.assertIn("captured", b)

    def test_product_build_no_git(self):
        nogit = tempfile.mkdtemp(prefix="mstack-nogit-")
        try:
            b = eval_loop.product_build(nogit)
        finally:
            shutil.rmtree(nogit, ignore_errors=True)
        self.assertIsNone(b["commit"])
        self.assertNotIn("dirty", b)

    def test_status_json_includes_build(self):
        self.write_round_views(1, self.commit1)
        self.write_round_views(2, self.commit1)
        r = subprocess.run(
            [sys.executable, LOOP, "status", "--json", "--dir", self.review],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(r.stdout)
        self.assertEqual(data["rounds"][0]["build"]["commit"], self.commit1)
        self.assertEqual(data["rounds"][1]["build"]["commit"], self.commit1)

    def test_report_same_build_and_warning(self):
        self.write_round_views(1, self.commit1, changes="- Starting point.")
        self.write_round_views(2, self.commit1, changes="- Small copy tweak.")
        self.write_round_views(3, self.commit2, changes="- No product change since round 2.")
        p = eval_loop.Project(self.review)
        path, _ = report.build(p)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("same build as round 1", html)
        short1, short2 = self.commit1[:7], self.commit2[:7]
        self.assertIn(short2, html)
        self.assertIn("the change note says nothing changed", html.lower())
        self.assertIn(short1, html)
        self.assertIn(short2, html)


if __name__ == "__main__":
    unittest.main()
