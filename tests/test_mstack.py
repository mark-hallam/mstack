#!/usr/bin/env python3
"""Self-test for the mstack index skill and ping-me: on and off switches, the session start rules, the
private journal, "review my skills", learned rules, notifications, and the setup for Claude Code hooks,
Codex and Cursor.

Everything runs in a throwaway folder: MSTACK_HOME points there, settings files are temporary copies, and
notifications go to a stand-in command instead of the real desktop. A local web server stands in for ntfy.

  python3 tests/test_mstack.py
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "skills", "mstack", "scripts", "mstack.py")
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def main():
    work = tempfile.mkdtemp(prefix="mstack-test-")
    sent = os.path.join(work, "sent.txt")
    env = dict(os.environ, MSTACK_HOME=os.path.join(work, "home"),
               MSTACK_NOTIFY_COMMAND='printf "%%s|%%s\\n" "$MSTACK_TITLE" "$MSTACK_MESSAGE" >> %s' % sent)

    def run(*args, stdin=None, expect=0):
        r = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, env=env, input=stdin,
                           timeout=60)
        if r.returncode != expect:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  mstack.py %s exited %d, expected %d" % (" ".join(args), r.returncode, expect))
        return r.stdout

    def pings():
        if not os.path.exists(sent):
            return []
        with open(sent) as fh:
            return fh.read().splitlines()

    try:
        # on and off
        names = [s["name"] for s in json.loads(run("skills", "--json"))["skills"]]
        check({"mstack", "ping-me", "outcome-first", "multi-evaluator"} <= set(names), "every skill is listed")
        run("enabled", "ping-me")
        check(True, "ping-me is on by default")
        start = run("session-start")
        check("ping me" in start and "PushNotification" in start, "session start switches ping me on")
        check("outcome first" in start and "multi-evaluator" in start, "session start lists the other skills")
        run("disable", "ping-me")
        run("enabled", "ping-me", expect=1)
        check(json.load(open(os.path.join(work, "home", "config.json")))["disabled"] == ["ping-me"],
              "disable writes ~/.mstack/config.json")
        start = run("session-start")
        check("PushNotification" not in start and "Switched off by the person (do not use): ping-me" in start,
              "a switched off skill leaves the session start rules")
        run("ping", "should not arrive")
        check(pings() == [], "no ping while ping-me is off")
        run("enable", "ping-me")
        run("disable", "no-such-skill", expect=2)
        check(True, "an unknown skill is refused")
        check("run only:" in start and "disable <skill>" in start and "Never edit CLAUDE.md" in start,
              "the session start rules say the off switch is the config file and nothing else")

        # the off path touches nothing but ~/.mstack/config.json (a stand-in HOME with the usual files)
        fake_home = os.path.join(work, "fake-home")
        for rel, body in (("CLAUDE.md", "# mine\n"), (".claude/settings.json", "{}\n"), (".codex/AGENTS.md", "# mine\n"),
                          (".codex/config.toml", 'model = "x"\n')):
            os.makedirs(os.path.dirname(os.path.join(fake_home, rel)), exist_ok=True)
            with open(os.path.join(fake_home, rel), "w") as fh:
                fh.write(body)
        home2 = os.path.join(fake_home, ".mstack")
        env2 = dict(env, HOME=fake_home, MSTACK_HOME=home2)

        def listing():
            found = {}
            for base, _, names in os.walk(fake_home):
                for n in names:
                    path = os.path.join(base, n)
                    with open(path, "rb") as fh:
                        found[os.path.relpath(path, fake_home)] = fh.read()
            return found
        before = listing()
        subprocess.run([sys.executable, TOOL, "disable", "outcome-first"], capture_output=True, env=env2, check=True)
        subprocess.run([sys.executable, TOOL, "enable", "outcome-first"], capture_output=True, env=env2, check=True)
        after = listing()
        new_files = set(after) - set(before)
        changed = [k for k in before if after.get(k) != before[k]]
        check(new_files == {os.path.join(".mstack", "config.json")} and not changed,
              "the off switch writes only config.json and changes no other file in the home")

        # ping me
        run("ping", "Need your OK to publish: 2 options in the chat", "--title", "mStack")
        check(pings()[-1] == "mStack|Need your OK to publish: 2 options in the chat", "ping sends the message")
        run("ping", "x" * 400)
        check(len(pings()[-1].split("|", 1)[1]) == 200, "a ping is cut to 200 characters")
        run("ping", "hook", stdin=json.dumps({"hook_event_name": "Notification", "cwd": "/tmp/shop",
                                              "message": "Claude needs your permission to use Bash",
                                              "notification_type": "permission_prompt"}))
        check(pings()[-1] == "Claude needs you: shop|Waiting for you in shop",
              "the Claude Code Notification hook pings, without the agent's words (reply text is private by default)")
        run("ping", "hook", stdin=json.dumps({"hook_event_name": "Stop", "cwd": "/tmp/shop",
                                              "last_assistant_message": "Done: the site is live."}))
        check(pings()[-1] == "Claude finished: shop|Turn finished in shop", "the Claude Code Stop hook pings, without the reply text")
        run("ping", "codex-event", json.dumps({"type": "agent-turn-complete", "cwd": "/tmp/api",
                                               "last-assistant-message": "All tests pass."}))
        check(pings()[-1] == "Codex finished: api|Turn finished in api", "the Codex notify event pings, without the reply text")
        n = len(pings())
        run("ping", "codex-event", json.dumps({"type": "something-else"}))
        check(len(pings()) == n, "other Codex events do not ping")

        # ntfy only when the person sets it up
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got.append((self.path, self.headers.get("Title"), self.rfile.read(int(self.headers["Content-Length"])).decode()))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run("ping", "no phone service yet")
        check(got == [], "nothing goes to a phone service by default")
        cfg = json.load(open(os.path.join(work, "home", "config.json")))
        cfg["ping"] = {"ntfy_topic": "private-topic", "ntfy_server": "http://127.0.0.1:%d" % srv.server_address[1]}
        json.dump(cfg, open(os.path.join(work, "home", "config.json"), "w"))
        run("ping", "Done: report ready", "--title", "mStack")
        check(got == [("/private-topic", "mStack", "Done: report ready")], "ntfy gets the ping once the person sets a topic")

        # the guided ntfy opt-in: shows first, writes and tests only with --write, removes again
        cfg["ping"] = {}
        json.dump(cfg, open(os.path.join(work, "home", "config.json"), "w"))
        server = "http://127.0.0.1:%d" % srv.server_address[1]
        out = run("setup", "ntfy", "--server", server)
        cfg2 = json.load(open(os.path.join(work, "home", "config.json")))
        check("Would set up" in out and "install the ntfy app" in out and not cfg2["ping"].get("ntfy_topic"),
              "setup ntfy shows the change and the steps without --write")
        out = run("setup", "ntfy", "--server", server, "--write")
        cfg2 = json.load(open(os.path.join(work, "home", "config.json")))
        topic = cfg2["ping"].get("ntfy_topic", "")
        check(topic.startswith("mstack-") and len(topic) >= 20 and cfg2["ping"]["ntfy_server"] == server,
              "setup ntfy --write writes a long random private topic")
        check(got[-1][0] == "/" + topic and "ntfy" in got[-1][2], "setup ntfy --write sends a test ping through it")
        run("setup", "ntfy", "--topic", "short", "--write", expect=1)
        check(True, "a guessable topic is refused")
        run("setup", "ntfy", "--remove", "--write")
        check(not json.load(open(os.path.join(work, "home", "config.json")))["ping"]["ntfy_topic"], "setup ntfy --remove turns it off")
        srv.shutdown()
        check("reaches their phone only while Remote Control" in run("session-start"),
              "the session start rules are honest about what reaches a phone")

        # the private journal, review my skills, learned rules
        for i in range(3):
            run("log", "outcome-first", "--outcome", "reached" if i else "partial", "--needed-user", "the deploy target",
                "--stalled", "waiting for tests" if i == 0 else "", "--correction", "use the staging site first")
        lines = open(os.path.join(work, "home", "journal", "outcome-first.jsonl")).read().splitlines()
        check(len(lines) == 3 and json.loads(lines[0])["outcome"] == "partial", "log keeps a private journal line per use")
        cfg["review_every"] = 3
        json.dump(cfg, open(os.path.join(work, "home", "config.json"), "w"))
        check("Review due: outcome-first (3 uses" in run("session-start"), "a review is offered after enough uses")
        rev = json.loads(run("review", "--json"))
        check(not os.path.exists(os.path.join(work, "home", "reviews")) and "Review due" in run("session-start"),
              "a plain review only reads: it writes nothing and the review is still due")
        r = rev["skills"]["outcome-first"]
        check(r["outcomes"] == {"reached": 2, "partial": 1, "not-reached": 0}, "review counts the outcomes")
        check(r["needed_user"] == [["the deploy target", 3]] and r["corrections"] == [["use the staging site first", 3]],
              "review gathers where it needed the person and their corrections")
        done = json.loads(run("review", "--done", "--json"))
        check(os.path.exists(done["review"]) and "the deploy target (3)" in open(done["review"]).read(),
              "review --done writes the evidence file")
        check("Review due" not in run("session-start"), "after review --done, it is no longer due")
        run("learn", "outcome-first", "Ask for the deploy target in the first batch of questions.")
        check("Ask for the deploy target" in run("learned", "outcome-first"), "learn keeps an accepted improvement")

        # setup for each agent: shows first, writes only with --write, keeps what was there
        settings = os.path.join(work, "claude-settings.json")
        json.dump({"model": "keep-me", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}},
                  open(settings, "w"))
        before = open(settings).read()
        out = run("setup", "claude-hooks", "--settings", settings)
        check("Would add" in out and open(settings).read() == before, "claude-hooks shows the change without --write")
        run("setup", "claude-hooks", "--settings", settings, "--write")
        s = json.load(open(settings))
        cmds = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
        check(s["model"] == "keep-me" and "echo mine" in cmds and any("ping hook" in c for c in cmds)
              and "Notification" in s["hooks"], "claude-hooks adds Notification and Stop and keeps the rest")
        check(os.path.exists(settings + ".mstack-backup") and os.path.exists(os.path.join(work, "home", "bin", "mstack.py")),
              "claude-hooks keeps a backup and a stable copy of the tool")
        run("setup", "claude-hooks", "--settings", settings, "--write")
        s = json.load(open(settings))
        check(len(s["hooks"]["Stop"]) == 2, "claude-hooks is safe to run twice")
        run("setup", "claude-hooks", "--settings", settings, "--write", "--remove")
        s = json.load(open(settings))
        check(s["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
              "claude-hooks --remove takes out only mStack's hooks")

        codex = os.path.join(work, "codex", "config.toml")
        os.makedirs(os.path.dirname(codex))
        open(codex, "w").write('model = "x"\n\n[profiles.fast]\nmodel = "y"\n')
        run("setup", "codex", "--codex-config", codex, "--write")
        text = open(codex).read()
        top = text.split("[profiles.fast]")[0]
        check('notify = ["python3"' in top and "codex-event" in top and 'model = "y"' in text,
              "codex setup adds notify at the top level and keeps the rest")
        agents = open(os.path.join(work, "codex", "AGENTS.md")).read()
        check(agents.count("<!-- mstack:start -->") == 1 and "ping me" in agents, "codex setup adds the routing block")
        run("setup", "codex", "--codex-config", codex, "--write")
        check(open(codex).read().count("notify =") == 1 and
              open(os.path.join(work, "codex", "AGENTS.md")).read().count("<!-- mstack:start -->") == 1,
              "codex setup is safe to run twice")
        other = os.path.join(work, "codex2", "config.toml")
        os.makedirs(os.path.dirname(other))
        mine = os.path.join(work, "my-notifier.txt")
        theirs = [sys.executable, "-c", "import sys; open(%r, 'a').write(sys.argv[1] + chr(10))" % mine]
        open(other, "w").write('model = "x"\nnotify = %s\n\n[profiles.fast]\nmodel = "y"\n' % json.dumps(theirs))
        out = run("setup", "codex", "--codex-config", other)
        check("then your own program" in out and "notify = %s" % json.dumps(theirs) in open(other).read(),
              "codex setup shows that an existing notify would be chained, and changes nothing without --write")
        run("setup", "codex", "--codex-config", other, "--write")
        text = open(other).read()
        m = re.search(r'(?m)^notify = (.*)$', text)
        chained = json.loads(m.group(1))
        check(chained[:1] == ["python3"] and "codex-event" in chained and "--also" in chained
              and json.loads(chained[-1]) == theirs and "# mstack-original-notify: " in text and 'model = "y"' in text,
              "codex setup --write chains the person's own notify after mStack's ping")
        n = len(pings())
        subprocess.run([sys.executable, TOOL] + chained[2:] + [json.dumps({"type": "agent-turn-complete", "cwd": "/tmp/x",
                                                                              "last-assistant-message": "Chained."})],
                       env=env, check=True, capture_output=True, timeout=60)
        check(len(pings()) == n + 1 and open(mine).read().count("agent-turn-complete") == 1,
              "the chained notify pings and then runs the person's own program with the event")
        run("setup", "codex", "--codex-config", other, "--write")
        check(len(re.findall(r"(?m)^notify =", open(other).read())) == 1, "a chained notify is not chained twice")
        odd = os.path.join(work, "codex3", "config.toml")
        os.makedirs(os.path.dirname(odd))
        open(odd, "w").write('notify = "not-a-list"\n')
        out = run("setup", "codex", "--codex-config", odd, "--write")
        check(open(odd).read() == 'notify = "not-a-list"\n' and "left it alone" in out,
              "a notify that cannot be read as a list is left alone")

        project = os.path.join(work, "project")
        run("setup", "cursor", "--project", project, "--write")
        rule = open(os.path.join(project, ".cursor", "rules", "mstack.mdc")).read()
        check(rule.startswith("---\n") and "alwaysApply: true" in rule and "outcome first" in rule,
              "cursor setup writes an always-applied rule")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
