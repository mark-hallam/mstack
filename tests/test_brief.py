#!/usr/bin/env python3
"""One-line briefs: the five kinds, the rules they carry, worktrees for workers, and starting one on a runner."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSTACK_DIR = os.path.join(ROOT, "skills", "mstack", "scripts")
BRIEF = os.path.join(MSTACK_DIR, "brief.py")
MSTACK = os.path.join(MSTACK_DIR, "mstack.py")
sys.path.insert(0, MSTACK_DIR)
import rules  # noqa: E402

RULES = """# Project rules

## Never touch
- Never touch the billing folder.

## Never print
- never print the family code (it is in the guard file, not here)

## Test targets
- persona kid: a seven year old who reads slowly
- engine: the staging copy on port 4100
"""
PRIVATE_TERM = "zebra-code-7"   # only here, to prove the brief never goes looking for it


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mstack-brief-")
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "work", "demo-app")
        os.makedirs(self.proj)
        write(os.path.join(self.proj, "HANDOFF.md"), "Where things stand.\n")
        self.env = dict(os.environ, MSTACK_HOME=self.home)
        self.old = os.environ.get("MSTACK_HOME")
        os.environ["MSTACK_HOME"] = self.home
        subprocess.run([sys.executable, os.path.join(MSTACK_DIR, "rules.py"), "init", "--project", self.proj],
                       env=self.env, capture_output=True, check=True)
        write(os.path.join(rules.project_dir(self.proj), "rules.md"), RULES)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("MSTACK_HOME", None)
        else:
            os.environ["MSTACK_HOME"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_brief(self, *args, script=BRIEF, env=None):
        return subprocess.run([sys.executable, script] + list(args), capture_output=True, text=True,
                              env=env or self.env, cwd=self.tmp)

    def make(self, kind, goal, *args, **kw):
        r = self.run_brief(kind, goal, "--project", self.proj, "--json", *args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        return data, read(data["path"])

    def test_each_kind(self):
        extra = {"tester": ["--target", "http://localhost:4100", "--persona", "kid"], "reviewer": [], "worker": [],
                 "research": [], "security": []}
        own = {"tester": ["a seven year old who reads slowly", "http://localhost:4100", "Blocker", "RELEASE", "HOLD"],
               "reviewer": ["verdict-format.md", "if_fixed", "blind"], "worker": ["side branch"],
               "research": ["VERIFIED", "UNCONFIRMED"], "security": ["never the value"]}
        for kind in extra:
            data, text = self.make(kind, "check the %s thing" % kind, *extra[kind])
            self.assertEqual(data["kind"], kind)
            self.assertTrue(data["path"].startswith(os.path.join(self.home, "briefs")))
            self.assertTrue(os.path.isfile(data["path"]))
            for want in own[kind] + ["Never touch the billing folder", "HANDOFF.md", '"status": "done"',
                                     "## Read these first", "## Rules", "## Your job", "## How to finish"]:
                self.assertIn(want, text, "%s brief lacks %r" % (kind, want))
            order = [text.index(h) for h in ("## Read these first", "## Rules", "## Your job", "## How to finish")]
            self.assertEqual(order, sorted(order))
            self.assertLess(text.index("HANDOFF.md"), text.index("## Rules"))
            self.assertTrue(text.startswith("# %s: check the %s thing" % (kind.capitalize(), kind)))
            self.assertIn("You are the %s for demo-app." % kind, text)
            self.assertEqual(data["rules_from"], [os.path.join(rules.project_dir(self.proj), "rules.md")])
            self.assertNotIn("Ask nothing", text)
        self.assertNotIn("verdict-format.md\n```", text)  # referenced, never pasted

    def test_unattended(self):
        _, text = self.make("research", "look", "--unattended")
        self.assertIn("Ask nothing", text)
        self.assertLess(text.index("Ask nothing"), text.index("## Your job"))

    def test_tester_needs_persona_and_target(self):
        r = self.run_brief("tester", "walk it", "--project", self.proj, "--target", "x", "--persona", "nobody")
        self.assertEqual(r.returncode, 1)
        self.assertIn("kid", r.stderr)
        r = self.run_brief("tester", "walk it", "--project", self.proj, "--persona", "kid")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--target", r.stderr)

    def test_previous_and_missing_read_file(self):
        prev = os.path.join(self.tmp, "last.md")
        write(prev, "1. Major: the button says Go\n")
        _, text = self.make("tester", "walk again", "--target", "x", "--previous", prev)
        self.assertIn("Regressed", text)
        self.assertIn(prev, text)
        r = self.run_brief("research", "x", "--project", self.proj, "--read", os.path.join(self.tmp, "nope.md"))
        self.assertEqual(r.returncode, 1)

    def test_no_rules_file_is_visible(self):
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        r = self.run_brief("research", "x", "--project", bare, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = read(json.loads(r.stdout)["path"])
        self.assertIn("No rules file yet for this project", text)

    def test_private_terms_are_not_hunted(self):
        _, text = self.make("research", "look")
        self.assertIn("family code", text)
        self.assertNotIn(PRIVATE_TERM, text)

    def git(self, *a, cwd):
        subprocess.run(["git"] + list(a), cwd=cwd, check=True, capture_output=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t" + "@" + "example.invalid",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t" + "@" + "example.invalid"))

    def test_worktree(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        r = self.run_brief("worker", "fix it", "--project", plain, "--worktree")
        self.assertEqual(r.returncode, 1)
        self.assertIn("git repository", r.stderr)
        repo = os.path.join(self.tmp, "repos", "app")
        os.makedirs(repo)
        self.git("init", "-q", cwd=repo)
        r = self.run_brief("worker", "fix it", "--project", repo, "--worktree")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no commits", r.stderr)
        write(os.path.join(repo, "a.txt"), "a")
        self.git("add", ".", cwd=repo)
        self.git("commit", "-q", "-m", "one", cwd=repo)
        r = self.run_brief("worker", "Fix the login page", "--project", repo, "--worktree", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        wt = os.path.join(os.path.realpath(os.path.dirname(repo)), "app-wt", "fix-the-login-page")
        self.assertEqual(data["worktree"], wt)
        self.assertTrue(os.path.isdir(wt))
        branch = subprocess.run(["git", "-C", wt, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "work/fix-the-login-page")
        text = read(data["path"])
        self.assertIn(wt, text)
        self.assertIn("work/fix-the-login-page", text)
        self.assertIn("work only in this folder", text.lower())
        again = self.run_brief("worker", "Fix the login page", "--project", repo, "--worktree")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already exists", again.stderr)

    def test_run_on_a_runner(self):
        script = os.path.join(self.tmp, "fake.sh")
        log = os.path.join(self.tmp, "seen.txt")
        write(script, '#!/bin/sh\n{ echo "ARGS: $*"; cat; } > "%s"\necho "reply ok"\n' % log)
        os.chmod(script, 0o755)
        env = dict(self.env, MSTACK_BRIEF_RUNNERS_JSON=json.dumps({"fake": {"command": [script]}}))
        data, text = self.make("research", "ask the runner", "--run", "fake", env=env)
        reply = data["run"]["reply"]
        self.assertEqual(reply, data["path"][:-3] + ".reply.md")
        self.assertIn("reply ok", read(reply))
        self.assertIn("## Your job", read(log))
        r = self.run_brief("research", "ask the runner", "--project", self.proj, "--run", "no-such-runner-here",
                           "--json", env=dict(self.env, MSTACK_BRIEF_RUNNERS_JSON=json.dumps(
                               {"no-such-runner-here": {"command": ["no-such-command-xyz"]}})))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no-such-command-xyz", r.stderr)
        self.assertTrue(any(f.endswith("research-ask-the-runner.md") for f in os.listdir(os.path.join(self.home, "briefs"))))

    def test_forwarded_from_mstack(self):
        a = self.run_brief("research", "same thing", "--project", self.proj, "--json")
        b = self.run_brief("brief", "research", "same thing", "--project", self.proj, "--json", script=MSTACK)
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(read(json.loads(a.stdout)["path"]), read(json.loads(b.stdout)["path"]))

    def test_session_start_note(self):
        out = self.run_brief("session-start", script=MSTACK, env=self.env).stdout
        self.assertNotIn("Starting another agent?", out)
        r = subprocess.run([sys.executable, MSTACK, "session-start"], capture_output=True, text=True, env=self.env,
                           cwd=self.proj)
        self.assertIn("Starting another agent? Write its brief with python3", r.stdout)
        self.assertIn("brief.py", r.stdout)


if __name__ == "__main__":
    unittest.main()
