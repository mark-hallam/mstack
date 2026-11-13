#!/usr/bin/env python3
"""Reviewer preflight and usage limits for the multi-evaluator loop.

Stub reviewers print a usage-limit message (or a good verdict), and a fake usage reading stands in for the
crew skill's usage.json, so nothing here calls a real AI or reads the person's real usage.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
sys.path.insert(0, SCRIPTS)
import availability  # noqa: E402

GOOD = '''import json, sys
sys.stdin.read()
print(json.dumps({"overall": 9, "journeys": [{"id": 1, "score": 9, "if_fixed": 9, "fixes": []}]}))
'''
LIMITED = '''import sys
sys.stdin.read()
print("Working on it...")
sys.stderr.write("ERROR: You've hit your usage limit. Try again in 2 hours 5 minutes.\\n")
sys.exit(1)
'''
GARBLED = '''import sys
sys.stdin.read()
print("I could not finish")
sys.exit(1)
'''
CODEX_SIGNED_OUT = '''import sys
if sys.argv[1:3] == ["login", "status"]:
    print("Not logged in")
    sys.exit(1)
print("{}")
'''


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def stub(bin_dir, name, body):
    path = os.path.join(bin_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!%s\n%s" % (sys.executable, body))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mstack-avail-")
        self.bin = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "mhome")
        self.codex_home = os.path.join(self.tmp, "codex")
        self.dir = os.path.join(self.tmp, "review")
        for d in (self.bin, os.path.join(self.home, "crew"), self.codex_home, self.dir):
            os.makedirs(d)
        stub(self.bin, "goodbot", GOOD)
        stub(self.bin, "limitbot", LIMITED)
        stub(self.bin, "garbledbot", GARBLED)
        stub(self.bin, "codex", CODEX_SIGNED_OUT)
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""), MSTACK_HOME=self.home,
                        CODEX_HOME=self.codex_home, MSTACK_CREW_NO_PROBE="1")
        self.saved_env = {k: os.environ.get(k) for k in ("PATH", "MSTACK_HOME", "CODEX_HOME", "MSTACK_CREW_NO_PROBE")}
        os.environ.update({k: self.env[k] for k in self.saved_env})
        self.notified = os.path.join(self.tmp, "notified.txt")

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def usage(self, runner, percent, resets_in=3600):
        path = os.path.join(self.home, "crew", "usage.json")
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        data[runner] = {"runner": runner, "at": availability.stamp(), "how": "test",
                        "windows": [{"window": "five_hour", "percent": percent, "resets_at": int(time.time() + resets_in),
                                     "resets": ""}]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def project(self, reviewers):
        cfg = {"name": "Availability test", "about": "A test product.", "persona": "a first-time user",
               "journeys": [{"id": 1, "name": "One", "task": "Do it."}],
               "views": [{"id": "v", "name": "V", "viewport": {"w": 1440, "h": 1000},
                          "steps": [{"do": "goto", "url": "http://127.0.0.1/"}]}],
               "reviewers": reviewers,
               "notify": {"command": [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write(sys.argv[2])",
                                      self.notified, "{message}"]}}
        with open(os.path.join(self.dir, "mstack-eval.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        rnd = os.path.join(self.dir, "rounds", "r1")
        os.makedirs(os.path.join(rnd, "shots"))
        os.makedirs(os.path.join(rnd, "verdicts"))
        with open(os.path.join(rnd, "changes.md"), "w", encoding="utf-8") as fh:
            fh.write("# Round 1\n")
        with open(os.path.join(rnd, "criteria.json"), "w", encoding="utf-8") as fh:
            json.dump([], fh)
        with open(os.path.join(rnd, "views.json"), "w", encoding="utf-8") as fh:
            json.dump({"views": cfg["views"], "build": None}, fh)
        with open(os.path.join(rnd, "shots", "v.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        r = self.loop("brief", "--round", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def loop(self, *args):
        return subprocess.run([sys.executable, LOOP] + list(args) + ["--dir", self.dir], capture_output=True, text=True,
                              env=self.env)

    def loop_json(self, *args, code=0):
        r = self.loop(*args, "--json")
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)


def cmd_reviewer(rid, maker, program, **kw):
    return dict({"id": rid, "name": rid, "maker": maker, "kind": "command", "timeout_minutes": 1,
                 "command": [program]}, **kw)


class LimitText(unittest.TestCase):
    def test_messages(self):
        hit = availability.limit_in_text("Claude AI usage limit reached|1794744000")
        self.assertEqual(hit["resets_at"], 1794744000)
        hit = availability.limit_in_text("You've hit your usage limit. Try again in 2 hours 5 minutes.")
        self.assertAlmostEqual(hit["resets_at"], time.time() + 2 * 3600 + 300, delta=60)
        hit = availability.limit_in_text("5-hour limit reached - resets 3pm")
        self.assertIsNone(hit["resets_at"])
        self.assertEqual(hit["resets"], "3pm")
        self.assertIsNotNone(availability.limit_in_text("Error 429: Too Many Requests"))
        self.assertIsNone(availability.limit_in_text("The reply did not parse"))
        self.assertIsNone(availability.limit_in_text(""))

    def test_runner(self):
        self.assertEqual(availability.runner_for({"command": ["codex", "exec"]}), "codex")
        self.assertEqual(availability.runner_for({"command": ["/opt/bin/claude", "-p"]}), "claude")
        self.assertIsNone(availability.runner_for({"command": ["cursor-agent", "-p"]}))
        self.assertEqual(availability.runner_for({"usage": "claude", "kind": "agent"}), "claude")
        self.assertIsNone(availability.runner_for({"usage": "none", "command": ["codex"]}))


class Preflight(Base):
    def test_states(self):
        self.usage("claude", 100)
        self.project([
            cmd_reviewer("full", "Anthropic", "goodbot", usage="claude"),
            cmd_reviewer("gone", "Other", "no-such-program-here"),
            cmd_reviewer("out", "OpenAI", "goodbot", signin_check=["false"]),
            cmd_reviewer("codexout", "OpenAI", "codex"),
            cmd_reviewer("fine", "Google", "goodbot"),
        ])
        data = self.loop_json("preflight", code=1)
        by = dict((c["id"], c) for c in data["reviewers"])
        self.assertEqual(by["full"]["state"], "paused")
        self.assertEqual(by["full"]["usage"]["percent"], 100)
        self.assertIn("resets at", by["full"]["why"])
        self.assertEqual(by["gone"]["state"], "missing")
        self.assertFalse(by["gone"]["found"])
        self.assertEqual(by["out"]["state"], "signed out")
        self.assertEqual(by["codexout"]["state"], "signed out")
        self.assertEqual(by["fine"]["state"], "ready")
        self.assertEqual(by["fine"]["usage"], "unknown")          # never a guessed number
        self.assertEqual(by["fine"]["signed_in"], "unknown")
        self.assertEqual(sorted(data["will_not_run"]), ["codexout", "full", "gone", "out"])
        text = self.loop("preflight").stdout
        self.assertIn("will not run", text)

    def test_brief_reports_preflight(self):
        self.usage("claude", 100)
        self.project([cmd_reviewer("full", "Anthropic", "goodbot", usage="claude"), cmd_reviewer("fine", "OpenAI", "goodbot")])
        data = self.loop_json("brief", "--round", "1")
        self.assertEqual(data["preflight"]["will_not_run"], ["full"])
        self.assertIn("preflight: will not run: full", self.loop("brief", "--round", "1").stdout)


class LimitDuringRound(Base):
    def test_enough_left_continues_short_one(self):
        self.project([cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("b", "OpenAI", "goodbot"),
                      cmd_reviewer("c", "Google", "limitbot")])
        data = self.loop_json("review", "--round", "1")
        self.assertTrue(data["results"]["c"]["paused"])
        self.assertIn("paused: usage limit, resets at", data["results"]["c"]["problem"])
        self.assertTrue(data["availability"]["enough"])
        self.assertFalse(data["availability"]["choice_needed"])
        rec = json.loads(read(os.path.join(self.dir, "rounds", "r1", "availability", "c.paused.json")))
        self.assertEqual(rec["reason"], "usage limit")
        self.assertNotIn("c", os.listdir(os.path.join(self.dir, "rounds", "r1", "verdicts")))
        st = self.loop_json("status")
        self.assertTrue(st["availability"]["short"])
        self.assertEqual(st["rounds"][0]["missing_verdicts"], [])
        self.assertNotIn("review --round 1 --only c", st["next"])
        self.assertTrue(st["rounds"][0]["ready"], st["rounds"][0]["not_ready_because"])
        self.loop("report", "--no-notify")
        page = read(os.path.join(self.dir, "report.html"))
        self.assertIn("Short one reviewer this round.", page)
        self.assertIn("paused: usage limit", page)
        self.assertFalse(os.path.exists(self.notified))

    def test_same_maker_left_is_not_enough(self):
        self.project([cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("a2", "Anthropic", "goodbot"),
                      cmd_reviewer("c", "OpenAI", "limitbot")])
        data = self.loop_json("review", "--round", "1", code=3)
        self.assertFalse(data["availability"]["enough"])
        self.assertTrue(data["availability"]["choice_needed"])

    def stopped(self, backup=True):
        rs = [cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("c", "OpenAI", "limitbot")]
        if backup:
            rs[1]["backup"] = "d"
            rs.append(cmd_reviewer("d", "OpenAI", "goodbot", enabled=False))
        self.project(rs)
        data = self.loop_json("review", "--round", "1", code=3)
        pl = data["availability"]
        self.assertTrue(pl["choice_needed"])
        self.assertEqual([c["id"] for c in pl["choices"]], ["wait", "backup", "fewer"])
        self.assertEqual(pl["choices"][1]["available"], backup)
        self.assertIn("choose --round 1 --choice", pl["how_to_answer"])
        self.assertTrue(os.path.exists(self.notified))
        self.assertIn("needs your choice", read(self.notified))
        st = self.loop_json("status")
        self.assertTrue(st["availability"]["choice_needed"])
        self.assertTrue(st["next"].startswith("ask the person"))
        self.assertFalse(st["rounds"][0]["ready"])
        text = self.loop("review", "--round", "1", "--only", "c")
        self.assertEqual(text.returncode, 3)
        self.assertIn("The round stops here", text.stdout)

    def test_stop_then_backup(self):
        self.stopped()
        out = self.loop_json("choose", "--round", "1", "--choice", "backup")
        self.assertEqual(out["choice"]["standins"], {"c": "d"})
        self.assertTrue(os.path.exists(os.path.join(self.dir, "rounds", "r1", "briefs", "d.md")))
        self.assertIn("review --round 1 --only d", self.loop_json("status")["next"])
        data = self.loop_json("review", "--round", "1", "--only", "d")
        self.assertTrue(data["results"]["d"]["ok"])
        st = self.loop_json("status")
        self.assertEqual(st["rounds"][0]["missing_verdicts"], [])
        self.assertTrue(st["rounds"][0]["ready"], st["rounds"][0]["not_ready_because"])

    def test_stop_then_fewer(self):
        self.stopped(backup=False)
        r = self.loop("choose", "--round", "1", "--choice", "backup")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no backup reviewer", r.stderr)
        self.loop_json("choose", "--round", "1", "--choice", "fewer")
        st = self.loop_json("status")
        self.assertFalse(st["availability"]["choice_needed"])
        self.assertFalse(st["availability"]["counts_toward_ready"])
        self.assertFalse(st["rounds"][0]["ready"])
        self.assertTrue(any("does not count toward ready" in x for x in st["rounds"][0]["not_ready_because"]))
        self.loop("report", "--no-notify")
        self.assertIn("does not count toward ready for people", read(os.path.join(self.dir, "report.html")))

    def test_stop_then_wait(self):
        self.stopped()
        self.loop_json("choose", "--round", "1", "--choice", "wait")
        st = self.loop_json("status")
        self.assertIn("chose to wait", st["next"])
        self.assertIn("review --round 1 --only c", st["next"])
        self.assertEqual(st["rounds"][0]["missing_verdicts"], ["c"])

    def test_garbled_reply_with_full_usage_is_a_pause(self):
        self.usage("claude", 97)
        self.project([cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("b", "Google", "goodbot"),
                      cmd_reviewer("g", "OpenAI", "garbledbot", usage="claude")])
        data = self.loop_json("review", "--round", "1")
        self.assertTrue(data["results"]["g"]["paused"])
        self.assertIn("did not fit the format", data["results"]["g"]["was"])

    def test_garbled_reply_without_limit_is_still_a_failure(self):
        self.project([cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("g", "OpenAI", "garbledbot")])
        data = self.loop_json("review", "--round", "1", code=1)
        self.assertNotIn("paused", data["results"]["g"])
        self.assertFalse(data["availability"]["paused"])

    def test_paused_before_running(self):
        self.usage("codex", 100)
        self.project([cmd_reviewer("a", "Anthropic", "goodbot"), cmd_reviewer("b", "Google", "goodbot"),
                      cmd_reviewer("x", "OpenAI", "goodbot", usage="codex")])
        data = self.loop_json("review", "--round", "1")
        self.assertTrue(data["results"]["x"]["paused"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "rounds", "r1", "work", "x", "raw-reply.txt")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
