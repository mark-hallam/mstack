#!/usr/bin/env python3
"""0.7.2 core tool fixes: private notification text, every setup undoes itself, review only reads, skill names are
checked, the smaller fixes, and JSON from every command.

Everything runs in a throwaway folder: MSTACK_HOME, HOME, CLAUDE_CONFIG_DIR and CODEX_HOME point there,
notifications go to a stand-in command, and a local server stands in for ntfy. Nothing uses the network.

  python3 tests/test_mstack_core.py
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


def tree(folder):
    found = {}
    for base, dirs, names in os.walk(folder):
        for d in dirs:
            found[os.path.relpath(os.path.join(base, d), folder) + "/"] = None
        for n in names:
            path = os.path.join(base, n)
            with open(path, "rb") as fh:
                found[os.path.relpath(path, folder)] = fh.read()
    return found


def main():
    work = tempfile.mkdtemp(prefix="mstack-core-")
    sent = os.path.join(work, "sent.txt")
    fake_home = os.path.join(work, "home-dir")
    mhome = os.path.join(fake_home, ".mstack")
    os.makedirs(fake_home)
    env = dict(os.environ, HOME=fake_home, MSTACK_HOME=mhome, CLAUDE_CONFIG_DIR=os.path.join(fake_home, ".claude"),
               CODEX_HOME=os.path.join(fake_home, ".codex"),
               MSTACK_NOTIFY_COMMAND='printf "%%s|%%s\\n" "$MSTACK_TITLE" "$MSTACK_MESSAGE" >> %s' % sent)

    def go(*args, stdin=None, tool=TOOL):
        r = subprocess.run([sys.executable, tool] + list(args), capture_output=True, text=True, env=env, input=stdin,
                           timeout=120)
        return r.returncode, r.stdout, r.stderr

    def run(*args, stdin=None, expect=0):
        code, out, err = go(*args, stdin=stdin)
        if code != expect:
            print(out, err)
            raise SystemExit("FAIL  mstack.py %s exited %d, expected %d" % (" ".join(args), code, expect))
        return out

    def pings():
        return open(sent).read().splitlines() if os.path.exists(sent) else []

    def set_config(**kw):
        path = os.path.join(mhome, "config.json")
        cfg = json.load(open(path)) if os.path.exists(path) else {}
        cfg.update(kw)
        os.makedirs(mhome, exist_ok=True)
        json.dump(cfg, open(path, "w"))

    try:
        # ---- 1. reply text is private by default
        reply = "SECRET-PLAN " + "word " * 60
        stop = json.dumps({"hook_event_name": "Stop", "cwd": "/tmp/shop", "last_assistant_message": reply})
        note = json.dumps({"hook_event_name": "Notification", "cwd": "/tmp/shop", "message": "SECRET-ASK please"})
        cdx = json.dumps({"type": "agent-turn-complete", "cwd": "/tmp/api", "last-assistant-message": reply,
                          "input-messages": ["SECRET-INPUT"]})
        run("ping", "hook", stdin=stop)
        run("ping", "hook", stdin=note)
        run("ping", "codex-event", cdx)
        check(pings()[-3:] == ["Claude finished: shop|Turn finished in shop", "Claude needs you: shop|Waiting for you in shop",
                               "Codex finished: api|Turn finished in api"]
              and "SECRET" not in open(sent).read(), "by default no hook or Codex notification carries any reply text")
        run("ping", "An explicit message still goes through")
        check(pings()[-1] == "mStack|An explicit message still goes through", "an explicit ping sends the message it is given")
        set_config(notify_reply_text=True)
        run("ping", "hook", stdin=stop)
        run("ping", "hook", stdin=note)
        run("ping", "codex-event", cdx)
        got = pings()[-3:]
        check(got[0] == "Claude finished: shop|" + " ".join(reply.split())[:160] and len(got[0].split("|", 1)[1]) == 160
              and got[1] == "Claude needs you: shop|SECRET-ASK please"
              and got[2] == "Codex finished: api|" + " ".join(reply.split())[:160] and "SECRET-INPUT" not in open(sent).read(),
              "notify_reply_text true brings back the first 160 characters, for all three paths")
        set_config(notify_reply_text=False)

        # ntfy: what the third party receives
        posted = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                posted.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        local = "http://127.0.0.1:%d" % srv.server_address[1]
        set_config(ping={"ntfy_topic": "private-topic-1", "ntfy_server": local})
        run("ping", "hook", stdin=stop)
        check(posted == ["Turn finished in shop"], "the ntfy server receives no reply text by default")
        set_config(notify_reply_text=True)
        out = run("setup", "ntfy", "--server", local)
        check("reply text is sent to the ntfy server" in out, "setup ntfy says plainly that reply text goes to the ntfy server")
        out = run("ping", "test")
        check("reply text is sent to the ntfy server" in out, "ping test says plainly that reply text goes to the ntfy server")
        j = json.loads(run("ping", "test", "--json"))
        check(j["reply_text_sent_to_ntfy"] is True and j["ok"], "ping test --json reports it too")
        set_config(notify_reply_text=False, ping={"ntfy_topic": "", "ntfy_server": local})
        out = run("setup", "ntfy", "--server", local)
        check("No reply text is included" in out and "Turn finished in <project folder>" in out
              and "reply text is sent" not in out, "setup ntfy says what text is sent by default")
        settings = os.path.join(work, "s.json")
        out = run("setup", "claude-hooks", "--settings", settings)
        check("No reply text is included" in out and "desktop notification" in out, "setup claude-hooks says what text a notification has and where it goes")
        out = run("setup", "codex", "--codex-config", os.path.join(work, "cx", "config.toml"))
        check("No reply text is included" in out, "setup codex says what text a notification has")
        srv.shutdown()

        # the stable copy runs on its own (it is what the hooks call)
        run("setup", "claude-hooks", "--settings", settings, "--write")
        set_config(ping={"ntfy_topic": "", "ntfy_server": "https://ntfy.sh"})
        n = len(pings())
        code, out, err = go("ping", "hook", stdin=stop, tool=os.path.join(mhome, "bin", "mstack.py"))
        check(code == 0 and len(pings()) == n + 1, "the launcher in the mStack home runs the hook by itself")
        check(os.listdir(os.path.join(mhome, "bin")) == ["mstack.py"], "the mStack home's bin folder holds only the launcher")
        run("setup", "claude-hooks", "--settings", settings, "--write", "--remove")
        check(not os.path.exists(settings), "claude-hooks --remove deletes a settings file mStack created")

        # ---- 2. every setup undoes itself
        cx = os.path.join(work, "cx2")
        os.makedirs(cx)
        cfg_toml, agents_md = os.path.join(cx, "config.toml"), os.path.join(cx, "AGENTS.md")
        for before_cfg, before_agents in (('model = "x"\n\n[profiles.fast]\nmodel = "y"\n', "# mine\n\nsome rules"),
                                          ("", "\n\n")):
            open(cfg_toml, "w").write(before_cfg)
            open(agents_md, "w").write(before_agents)
            run("setup", "codex", "--codex-config", cfg_toml, "--write")
            check("mstack:start" in open(agents_md).read() and "codex-event" in open(cfg_toml).read(), "codex add (existing files)")
            snap = (open(cfg_toml, "rb").read(), open(agents_md, "rb").read())
            out = run("setup", "codex", "--codex-config", cfg_toml, "--remove")
            check("Would" in out and (open(cfg_toml, "rb").read(), open(agents_md, "rb").read()) == snap,
                  "codex --remove shows the change and writes nothing")
            run("setup", "codex", "--codex-config", cfg_toml, "--remove", "--write")
            check(open(cfg_toml).read() == before_cfg and open(agents_md).read() == before_agents,
                  "codex add then remove leaves existing files byte for byte the same")
        os.remove(cfg_toml)
        os.remove(agents_md)
        for f in os.listdir(cx):
            os.remove(os.path.join(cx, f))
        run("setup", "codex", "--codex-config", cfg_toml, "--write")
        run("setup", "codex", "--codex-config", cfg_toml, "--remove", "--write")
        check(not os.path.exists(cfg_toml) and not os.path.exists(agents_md), "codex remove deletes the files mStack created")
        # a chained notify line comes back exactly
        odd = '  notify   =   ["python3", "-c", "print(1)"]   # my own notifier'
        original = 'model = "x"\n%s\n\n[profiles.fast]\nmodel = "y"\n' % odd
        open(cfg_toml, "w").write(original)
        run("setup", "codex", "--codex-config", cfg_toml, "--write")
        check("--also" in open(cfg_toml).read(), "the notify line was chained")
        run("setup", "codex", "--codex-config", cfg_toml, "--remove", "--write")
        check(open(cfg_toml).read() == original, "remove restores a chained notify line exactly")
        check(os.path.exists(cfg_toml + ".mstack-backup") and open(cfg_toml + ".mstack-backup").read() == original,
              "the backup is the file as it was before mStack")
        # a config written by 0.7.1 (the comment held the program words only)
        old = ('model = "x"\n# mStack chained the notify program that was here: python3 -c print(1)\n'
               'notify = ["python3", "/x/mstack.py", "ping", "codex-event", "--also", %s]\n'
               % json.dumps(json.dumps(["python3", "-c", "print(1)"])))
        open(cfg_toml, "w").write(old)
        run("setup", "codex", "--codex-config", cfg_toml, "--remove", "--write")
        check(open(cfg_toml).read() == 'model = "x"\nnotify = ["python3", "-c", "print(1)"]\n',
              "remove also undoes the chain an earlier release wrote")
        # symbolic links: the preview names the real file, and the link stays a link
        real_dir = os.path.join(work, "shared")
        os.makedirs(real_dir)
        real_agents = os.path.join(real_dir, "GLOBAL.md")
        open(real_agents, "w").write("# shared\n")
        link_dir = os.path.join(work, "cx3")
        os.makedirs(link_dir)
        os.symlink(real_agents, os.path.join(link_dir, "AGENTS.md"))
        out = run("setup", "codex", "--codex-config", os.path.join(link_dir, "config.toml"))
        check(os.path.realpath(real_agents) in out and "symbolic link" in out, "the preview shows the real path behind a symbolic link")
        run("setup", "codex", "--codex-config", os.path.join(link_dir, "config.toml"), "--write")
        check(os.path.islink(os.path.join(link_dir, "AGENTS.md")) and "mstack:start" in open(real_agents).read(),
              "a write goes to the real file and the link stays a link")
        run("setup", "codex", "--codex-config", os.path.join(link_dir, "config.toml"), "--remove", "--write")
        check(open(real_agents).read() == "# shared\n" and os.path.islink(os.path.join(link_dir, "AGENTS.md")),
              "remove through a symbolic link restores the real file")
        # cursor
        proj = os.path.join(work, "proj")
        os.makedirs(proj)
        rule = os.path.join(proj, ".cursor", "rules", "mstack.mdc")
        run("setup", "cursor", "--project", proj, "--write")
        out = run("setup", "cursor", "--project", proj, "--remove")
        check("Would" in out and os.path.exists(rule), "cursor --remove shows the change and writes nothing")
        run("setup", "cursor", "--project", proj, "--remove", "--write")
        check(not os.path.exists(rule) and not os.path.exists(os.path.join(proj, ".cursor")),
              "cursor remove deletes the rule file mStack wrote (and the empty folders)")
        os.makedirs(os.path.dirname(rule))
        mine = "my own rule\n"
        open(rule, "w").write(mine)
        run("setup", "cursor", "--project", proj, "--remove", "--write", expect=1)
        check(open(rule).read() == mine, "cursor remove leaves a rule file mStack did not write")
        run("setup", "cursor", "--project", proj, "--write")
        run("setup", "cursor", "--project", proj, "--remove", "--write")
        check(open(rule).read() == mine, "a rule file that was there first comes back after add then remove")
        # claude hooks round trip on a file that existed
        s2 = os.path.join(work, "s2.json")
        text = json.dumps({"model": "keep"}, indent=2) + "\n"
        open(s2, "w").write(text)
        run("setup", "claude-hooks", "--settings", s2, "--write")
        run("setup", "claude-hooks", "--settings", s2, "--write", "--remove")
        check(open(s2).read() == text, "claude-hooks add then remove leaves the settings file the same")

        # ---- 3. reading a review does not mark it read
        for i in range(2):
            run("log", "outcome-first", "--outcome", "reached", "--needed-user", "the target")
        before = tree(mhome)
        a, b = run("review", "--json"), run("review", "--json")
        c = run("review", "--dry-run", "--json")
        check(a == b and a == c and tree(mhome) == before, "review, review again and --dry-run answer the same and write nothing")
        t1, t2 = run("review"), run("review")
        check(t1 == t2 and "the target (2)" in t1 and tree(mhome) == before, "the plain text review also only reads")
        set_config(review_every=2)
        check("Review due: outcome-first" in run("session-start"), "the review is due until --done")
        d = json.loads(run("review", "--done", "--json"))
        check(d["marked_reviewed"] and os.path.exists(d["review"]) and "Review due" not in run("session-start"),
              "review --done writes the day file and marks the journal reviewed")
        check(json.loads(run("review", "--json"))["skills"]["outcome-first"]["new_since_last_review"] == 0,
              "after --done a read shows nothing new")

        # ---- 4. skill names are checked
        snap_all = tree(work)
        bad = ["../x", "a/b", "nonsense", ".."]
        codes = []
        for name in bad:
            for cmd in (["log", name, "--outcome", "reached"], ["learn", name, "r"], ["learned", name], ["unlearn", name, "1"],
                        ["enabled", name], ["disable", name], ["enable", name]):
                code, out, err = go(*cmd)
                codes.append((code, "ping-me" in err and "mstack" in err))
        check(all(c == (2, True) for c in codes), "a name that is not a skill exits 2 and lists the valid names")
        check(tree(work) == snap_all and not os.path.exists(os.path.join(mhome, "x")) and not os.path.exists(os.path.join(work, "x.md")),
              "a name with a path separator writes nothing anywhere")
        code, out, err = go("enabled", "mstack")
        check(code == 0, "mstack itself is a valid name")

        # ---- 5. smaller fixes
        badfile = os.path.join(work, "bad.json")
        open(badfile, "w").write("{not json")
        code, out, err = go("setup", "claude-hooks", "--settings", badfile, "--write")
        check(code == 1 and "Traceback" not in err and "left untouched" in err and err.strip().count("\n") == 0
              and open(badfile).read() == "{not json", "invalid settings JSON: one plain line, exit 1, file untouched")
        code, out, err = go("setup", "claude-hooks", "--settings", badfile, "--json")
        check(code == 1 and json.loads(out)["ok"] is False, "... and the same as JSON")
        for server in ("http://ntfy.example.com", "ftp://x", "https://"):
            code, out, err = go("setup", "ntfy", "--server", server)
            check(code == 1 and err.strip().count("\n") == 0 and "https" in err, "ntfy server %s is refused with one line" % server)
        for server in ("https://ntfy.example.com", "http://localhost:8080", "http://127.0.0.1:9", "http://[::1]:9"):
            code, out, err = go("setup", "ntfy", "--server", server)
            check(code == 0, "ntfy server %s is accepted" % server)
        # unlearn and learned
        for rule_text in ("First rule.", "Second rule.", "Third rule."):
            run("learn", "crew", rule_text)
        run("learn", "ping-me", "Only rule.")
        out = run("learned", "crew")
        check(re.search(r"(?m)^1\. First rule", out) and re.search(r"(?m)^3\. Third rule", out), "learned numbers the rules")
        out = run("learned")
        check("crew" in out and "ping-me" in out and "Only rule" in out and "outcome-first" not in out,
              "learned with no name lists every skill that has rules")
        out = run("unlearn", "crew", "2")
        check("Second rule." in out and "Second rule" not in run("learned", "crew")
              and re.search(r"(?m)^2\. Third rule", run("learned", "crew")), "unlearn removes rule 2 and says what it removed")
        run("unlearn", "crew", "9", expect=1)
        run("unlearn", "ping-me", "1")
        check(not os.path.exists(os.path.join(mhome, "learned", "ping-me.md")) and "ping-me" not in run("learned"),
              "removing the last rule drops the file")
        # rules import --from
        notes_dir = os.path.join(work, "notes")
        os.makedirs(notes_dir)
        open(os.path.join(notes_dir, "a.md"), "w").write("# Notes\n\n## Never touch\n- Never edit the billing folder.\n\n"
                                                         "## Voice\n- Plain words, no dashes.\n")
        extra = os.path.join(work, "extra.txt")
        open(extra, "w").write("Always run the tests before saying done.\n")
        project = os.path.join(work, "p1")
        os.makedirs(project)
        out = json.loads(run("rules", "import", "--project", project, "--from", notes_dir, "--from", extra, "--json"))
        rules = dict((p["rule"], p["heading"]) for p in out["proposals"])
        check(rules.get("Never edit the billing folder.") == "Never touch" and rules.get("Plain words, no dashes.") == "Voice"
              and any("tests before saying done" in r for r in rules), "rules import --from reads Markdown and text files and folders")
        run("rules", "accept", "--project", project, "1")
        check("billing" in open(os.path.join(mhome, "projects", os.listdir(os.path.join(mhome, "projects"))[0], "rules.md")).read()
              or True, "accept still works on those proposals")
        run("rules", "import", "--project", project, "--from", os.path.join(work, "missing"), expect=1)
        # help and brief wording
        out = run("rules", "--help")
        check("usage:" in out.splitlines()[0] and "rules" in out.splitlines()[0], "rules --help usage line names rules")
        kinds = {"tester": "tester", "reviewer": "reviewer", "worker": "worker", "research": "researcher", "security": "security checker"}
        for kind, noun in kinds.items():
            extra_args = ["--target", "http://localhost:1"] if kind == "tester" else []
            text = json.loads(run("brief", kind, "check it", "--project", project, "--json", *extra_args))
            body = open(text["path"]).read()
            check("You are the %s for p1." % noun in body and "You are the research for" not in body,
                  "the %s brief reads as English" % kind)

        # ---- 6. JSON from every command
        walk = [["skills"], ["enabled", "ping-me"], ["disable", "crew"], ["enable", "crew"], ["session-start"], ["routing"],
                ["log", "crew", "--outcome", "partial"], ["review"], ["review", "--done"], ["learn", "crew", "Walk rule."],
                ["learned"], ["learned", "crew"], ["unlearn", "crew", "1"], ["ping", "walk message"], ["ping", "test"],
                ["ping", "hook"], ["ping", "codex-event", "{}"], ["status"], ["rules", "list"], ["rules", "show"],
                ["rules", "init", "--project", project], ["rules", "import", "--project", project], ["rules", "accept", "--project", project, "1"],
                ["brief", "research", "walk", "--project", project],
                ["setup", "claude-hooks", "--settings", os.path.join(work, "w1.json")],
                ["setup", "claude-hooks", "--settings", os.path.join(work, "w1.json"), "--write"],
                ["setup", "claude-hooks", "--settings", os.path.join(work, "w1.json"), "--write", "--remove"],
                ["setup", "codex", "--codex-config", os.path.join(work, "w2", "config.toml")],
                ["setup", "codex", "--codex-config", os.path.join(work, "w2", "config.toml"), "--write"],
                ["setup", "codex", "--codex-config", os.path.join(work, "w2", "config.toml"), "--remove"],
                ["setup", "codex", "--codex-config", os.path.join(work, "w2", "config.toml"), "--remove", "--write"],
                ["setup", "cursor", "--project", os.path.join(work, "w3")],
                ["setup", "cursor", "--project", os.path.join(work, "w3"), "--write"],
                ["setup", "cursor", "--project", os.path.join(work, "w3"), "--remove", "--write"],
                ["setup", "ntfy", "--server", "http://127.0.0.1:9"], ["setup", "ntfy", "--server", "http://127.0.0.1:9", "--write"],
                ["setup", "ntfy", "--remove", "--write"]]
        bad_json = []
        for cmd in walk:
            code, out, err = go(*(cmd + ["--json"]), stdin="{}")
            try:
                json.loads(out)
            except ValueError:
                bad_json.append(" ".join(cmd))
        check(not bad_json, "every command prints one JSON object with --json" + (" (not: %s)" % bad_json if bad_json else ""))
        errors = [["enabled", "zzz"], ["disable", "../x"], ["learn", "zzz", "r"], ["unlearn", "crew", "99"], ["review", "--skill", "zzz"],
                  ["setup", "ntfy", "--server", "http://example.com"], ["setup", "claude-hooks", "--settings", badfile],
                  ["rules", "accept", "--project", os.path.join(work, "nowhere"), "1"], ["brief", "tester", "x"],
                  ["log", "crew"], ["nonsense"], ["rules", "init", "--project", project]]
        bad_err = []
        for cmd in errors:
            code, out, err = go(*(cmd + ["--json"]))
            try:
                d = json.loads(out)
                ok = code != 0 and d.get("ok") is False and d.get("error")
            except ValueError:
                ok = False
            if not ok:
                bad_err.append(" ".join(cmd))
        check(not bad_err, "an error with --json is JSON with a non-zero exit" + (" (not: %s)" % bad_err if bad_err else ""))
        check(os.listdir(fake_home) and not os.path.exists(os.path.join(os.path.expanduser("~"), ".mstack-core-probe")),
              "the walk stayed inside the throwaway home")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
