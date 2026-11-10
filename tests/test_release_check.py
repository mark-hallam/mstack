#!/usr/bin/env python3
"""The release evidence step: a run against a stand-in Claude Code, the generated tables, and the gate."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tests", "release_check.py")
sys.path.insert(0, os.path.join(ROOT, "tests"))
import release_check  # noqa: E402

STAND_IN = r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
home = os.environ["CLAUDE_CONFIG_DIR"]
if a[:2] == ["plugin", "marketplace"]:
    sys.exit(3 if os.environ.get("STAND_IN_FAIL") else 0)
if a[:2] == ["plugin", "install"]:
    os.makedirs(os.path.join(home, "plugins", "cache", "mstack", "mstack", "9.9.9"))
    sys.exit(0)
if a and a[0] == "-p":
    seen = os.path.exists(os.path.join(home, ".credentials.json"))
    text = a[-1]
    if "heading out" in text:
        print("**mstack:ping-me** with mstack:outcome-first beside it. login seen: %s" % seen)
    elif "landing page" in text:
        print("I would use the multi-evaluator skill, because mStack lists it.")
    elif "phone" in text:
        print("**mstack:crew**, not mstack:away-mode.")
    else:
        print("No skill fits.")
'''


def load(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def dump(data, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def run(*argv, **env):
    return subprocess.run([sys.executable, TOOL] + list(argv), capture_output=True, text=True,
                          env=dict(os.environ, **env))


class ReleaseCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mstack-release-test-")
        self.claude = os.path.join(self.tmp, "claude")
        with open(self.claude, "w", encoding="utf-8") as fh:
            fh.write(STAND_IN)
        os.chmod(self.claude, os.stat(self.claude).st_mode | stat.S_IEXEC)
        self.login = os.path.join(self.tmp, "login.json")
        with open(self.login, "w", encoding="utf-8") as fh:
            fh.write('{"stand": "in"}')
        self.phrases = os.path.join(self.tmp, "phrases.json")
        spec = json.loads(load(os.path.join(ROOT, "tests", "release_phrases.json")))
        spec["phrases"] = spec["phrases"][:4]
        dump(spec, self.phrases)
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_picked(self):
        names = ["away-mode", "crew", "mstack", "outcome-first", "ping-me"]
        self.assertEqual(release_check.picked("**mstack:outcome-first**: then mstack:crew", names), "outcome-first")
        self.assertEqual(release_check.picked("**mstack:mstack**, its index covers `mstack status`", names), "mstack")
        self.assertEqual(release_check.picked("mStack's away-mode skill fits", names), "away-mode")
        self.assertEqual(release_check.picked("Nothing installed fits this.", names), None)

    def test_run_scores_and_removes_the_login(self):
        done = run("run", "--source", ROOT, "--out", self.out, "--claude", self.claude, "--phrases", self.phrases,
                   "--login-file", self.login, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.loads(done.stdout)
        got = {r["id"]: (r["picked"], r["right"]) for r in data["rows"]}
        self.assertEqual(got, {"p1": ("ping-me", True), "p2": ("multi-evaluator", True), "p3": ("crew", False),
                               "p4": (None, False)})
        self.assertEqual((data["right"], data["total"], data["version"]), (2, 4, "9.9.9"))
        self.assertEqual(data["source"], "the release candidate folder")
        self.assertTrue(data["login_removed"])
        self.assertIn("login seen: True", load(os.path.join(self.out, "p1.out")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "claude-home")), "the clean profile is deleted")
        self.assertNotIn(ROOT, json.dumps(data["rows"]) + data["source"], "no folder path in the record")

    def test_a_failed_install_still_removes_the_login(self):
        done = run("run", "--source", "someone/somewhere", "--out", self.out, "--claude", self.claude,
                   "--phrases", self.phrases, "--login-file", self.login, "--json", STAND_IN_FAIL="1")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(json.loads(done.stdout)["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "claude-home")))

    def copy_of_docs(self, version):
        root = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(root, "docs"))
        os.makedirs(os.path.join(root, ".claude-plugin"))
        dump({"version": version}, os.path.join(root, ".claude-plugin", "plugin.json"))
        for rel in ("README.md", os.path.join("docs", "evidence.md")):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write("before\n%s\nold\n%s\nafter\n" % (release_check.START, release_check.END))
        return root

    def test_write_then_gate(self):
        root = self.copy_of_docs("9.9.9")
        self.assertEqual(run("gate", "--root", root).returncode, 1, "no result recorded yet")
        result = os.path.join(self.tmp, "result.json")
        rows = [{"id": "p1", "phrase": "x", "expected": ["crew"], "picked": "crew", "right": True}]
        dump({"version": "9.9.9", "date": "2026-11-10", "source": "the release candidate folder",
              "agent": "Claude Code", "model": "sonnet", "right": 1, "total": 1, "rows": rows,
              "out": "/somewhere/private"}, result)
        done = run("write", "--result", result, "--root", root, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        readme = load(os.path.join(root, "README.md"))
        page = load(os.path.join(root, "docs", "evidence.md"))
        self.assertIn("**1 of 1** plain phrases reached the right skill on a clean install of 9.9.9 (10 November 2026)", readme)
        self.assertIn("| 9.9.9 | 10 November 2026 | the release candidate folder | Claude Code (sonnet) | **1 of 1** |", page)
        self.assertTrue(readme.startswith("before\n") and readme.endswith("after\n") and "old" not in readme)
        self.assertNotIn("private", load(release_check.store(root)))
        self.assertEqual(run("gate", "--root", root).returncode, 0)
        run("write", "--result", result, "--root", root)
        self.assertEqual(len(json.loads(load(release_check.store(root)))["results"]), 1, "the same run is recorded once")
        dump({"version": "9.9.10"}, os.path.join(root, ".claude-plugin", "plugin.json"))
        gate = run("gate", "--root", root, "--json")
        self.assertEqual(gate.returncode, 1, "a new version needs a new run")
        self.assertIn("9.9.10", json.loads(gate.stdout)["problems"][0])

    def test_the_repository_has_evidence_for_its_version(self):
        done = run("gate")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
