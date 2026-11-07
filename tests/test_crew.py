#!/usr/bin/env python3
"""Self-test for crew: sources become jobs, the cheapest fitting runner, the 85% stop and ask, the conservative
fallback when usage cannot be read, no two jobs on the same files, the stop file and pause, a run with a
stand-in runner on a throwaway git repository, the digest, and an install dry run that writes nothing.

Everything runs in a throwaway folder (MSTACK_HOME, CODEX_HOME, MSTACK_LAUNCH_AGENTS). The stand-in runner
prints the same stream-json shape as Claude Code, including a rate_limit_event, and makes one commit.
No model, no network, no real launchd or crontab.

  python3 tests/test_crew.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "skills", "crew", "scripts", "crew.py")
LOOP = os.path.join(ROOT, "skills", "multi-evaluator", "scripts", "eval_loop.py")
LOCKS = os.path.join(ROOT, "skills", "mstack", "scripts")
failures = []

FAKE_RUNNER = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
prompt = args[0] if args and not args[0].startswith("-") else ""
pct = float(os.environ.get("FAKE_PCT", "40"))
print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
    "five_hour": {"utilization": pct / 100.0, "resetsAt": 4102444800}, "seven_day": {"utilization": 0.3, "resetsAt": 4102444800}}}}))
mode = os.environ.get("FAKE_MODE", "done")
if "Reply with the single word ok" in prompt:
    print(json.dumps({"type": "result", "result": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}, "total_cost_usd": 0.0}))
    sys.exit(0)
if mode == "done":
    with open("crew-made.txt", "w") as fh:
        fh.write("made by the stand-in runner\n")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", "crew: stand-in change"], check=True)
    block = {"status": "done", "evidence": ["crew-made.txt written"], "note": "stand-in finished"}
elif mode == "question":
    block = {"status": "question", "question": "Which colour for the button?", "default": "blue", "note": "needs a choice"}
else:
    block = {"status": "blocked", "note": "could not find the file"}
print(json.dumps({"type": "result", "result": "All done.\n" + json.dumps(block), "num_turns": 3, "duration_ms": 1200,
                  "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 0},
                  "total_cost_usd": 0.01}))
'''

VERDICT = {"reviewer": "x", "round": 1, "overall": 6, "top_fixes": [], "broken": [],
           "journeys": [{"id": 1, "name": "Sign up", "score": 5, "if_fixed": 9, "fixes": [
               {"severity": "high", "where": "the form", "problem": "no error shown", "fix": "Show the error under the field"}]},
                        {"id": 2, "name": "Export", "score": 8, "if_fixed": 9, "fixes": [
                            {"severity": "low", "where": "the button", "problem": "", "fix": "Rename Export to Download"}]}]}


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True).stdout.strip()


def main():
    work = tempfile.mkdtemp(prefix="mstack-crew-test-")
    home = os.path.join(work, "home")
    repo = os.path.join(work, "proj")
    os.makedirs(os.path.join(repo, "docs"))
    subprocess.run(["git", "-C", repo, "init", "-q", "-b", "main"], check=True)
    with open(os.path.join(repo, "docs", "PLAN.md"), "w") as fh:
        fh.write("# Plan\n- [ ] Fix the typo in docs/PLAN.md heading\n- [ ] Design the onboarding flow from first principles\n- [x] done\n")
    with open(os.path.join(repo, "shared.py"), "w") as fh:
        fh.write("x = 1\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", "init"], check=True)
    review = os.path.join(repo, "design-review", "rounds", "r1", "verdicts")
    os.makedirs(review)
    for who in ("claude", "codex"):
        with open(os.path.join(review, who + ".json"), "w") as fh:
            json.dump(dict(VERDICT, reviewer=who), fh)
    fake = os.path.join(work, "fake_runner.py")
    with open(fake, "w") as fh:
        fh.write(FAKE_RUNNER)
    codex_home = os.path.join(work, "codex")
    os.makedirs(os.path.join(codex_home, "sessions", "2026", "11", "04"))
    with open(os.path.join(codex_home, "sessions", "2026", "11", "04", "rollout-a.jsonl"), "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-11-04T10:00:00.000Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 90.0, "window_minutes": 300, "resets_at": 4102444800},
            "secondary": {"used_percent": 20.0, "window_minutes": 10080, "resets_at": 4102444800}}}}) + "\n")
    agents = os.path.join(work, "LaunchAgents")
    os.makedirs(agents)
    cfg = {"quiet_hours": {"start": "00:00", "end": "23:59"}, "usage_max_age_minutes": 100000,
           "runners": {"claude": {"command": [sys.executable, fake], "models": {"small": "haiku", "fast": "sonnet", "top": "opus"}},
                       "codex": {"command": [sys.executable, fake], "models": {}}},
           "projects": [{"id": "proj", "path": repo, "branch": "main", "stream": "products", "test": "test -f docs/PLAN.md",
                         "sources": [{"kind": "plan", "file": "docs/PLAN.md"}, {"kind": "evaluator", "dir": "design-review"},
                                     {"kind": "tests"}, {"kind": "daily", "id": "ideas", "at": "00:00", "tier": "small",
                                                         "title": "Mine three ideas", "prompt": "Write ideas.md"}]}]}
    os.makedirs(os.path.join(home, "crew"))
    with open(os.path.join(home, "crew", "config.json"), "w") as fh:
        json.dump(cfg, fh)
    env = dict(os.environ, MSTACK_HOME=home, CODEX_HOME=codex_home, MSTACK_LAUNCH_AGENTS=agents, MSTACK_CREW_NO_CAFFEINATE="1",
               MSTACK_CREW_NO_RENDER="1", MSTACK_CREW_NO_PING="1", MSTACK_CREW_AWAY="0", MSTACK_LAUNCHCTL="%s -c pass" % sys.executable,
               MSTACK_CRONTAB="%s -c pass" % sys.executable, FAKE_PCT="40", FAKE_MODE="done")

    def run(*args, expect=0, **extra):
        r = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, env=dict(env, **extra), timeout=120)
        if r.returncode != expect:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  crew.py %s exited %d, expected %d" % (" ".join(args), r.returncode, expect))
        return r.stdout

    def js(*args, **extra):
        return json.loads(run(*(list(args) + ["--json"]), **extra))

    try:
        # sources become jobs
        s = js("scan")
        titles = [a["title"] for a in s["added"]]
        check(len(s["added"]) == 5, "scan turned the plan, the review round and the daily job into 5 jobs (%d)" % len(s["added"]))
        check(any("Fix journey 1" in t and "2 review findings" in t for t in titles), "review fixes are batched per journey, agreed first")
        tiers = dict((a["title"], a["tier"]) for a in s["added"])
        check(tiers.get("Fix the typo in docs/PLAN.md heading") == "small" and tiers.get("Design the onboarding flow from first principles") == "top",
              "the tier is guessed from the work: a typo is small, a design is top")
        check(not any("tests pass" in t.lower() for t in titles), "passing tests add no job")
        check(len(js("scan")["added"]) == 0, "a second scan adds nothing twice")
        # the ranking and the runner choice
        n = js("next")
        check(n["next"]["source"] == "daily:ideas", "the daily job whose time has come runs first")
        check(n["runner"] == "claude", "the runner with the most headroom is chosen (claude 40 vs codex 90): %s" % n["runner"])
        # a run on the stand-in runner: side branch, commit as evidence, tokens recorded
        r = js("run", n["next"]["id"])
        check(r["state"] == "done" and any(e.startswith("commit ") for e in r["evidence"]), "the job finished with a commit as evidence")
        check(r["branch"] == "crew/" + n["next"]["id"] and git(repo, "branch", "--list", r["branch"]), "the work is on a side branch")
        check(not os.path.isdir(os.path.join(home, "crew", "worktrees", r["job"])), "the worktree is removed once its commits are on the branch")
        check(git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and not os.path.exists(os.path.join(repo, "crew-made.txt")),
              "the person's checkout is untouched")
        check(r["usage"].get("total_tokens") == 6500 and r["usage"].get("window_after") == 40.0, "tokens and the window after are recorded")
        u = js("usage")
        check(u["claude"]["reading"]["how"] == "rate_limit_event" and u["claude"]["headroom"] == 45.0, "the run's rate_limit_event became the reading")
        check(u["codex"]["mode"] == "ask" and "90" in u["codex"]["why"], "codex at 90 is at the reserve: stop and ask")
        # a question from the runner goes to the person, nothing is assumed
        r = js("run", FAKE_MODE="question")
        check(r["state"] == "question", "a runner's question parks the job")
        qs = json.loads(run("list"))["questions"]
        check(any(x["question"] == "Which colour for the button?" and x["default"] == "blue" for x in qs), "the question and its default are queued")
        run("answer", r["job"], "green")
        jb = next(j for j in json.loads(run("list"))["jobs"] if j["id"] == r["job"])
        check(jb["state"] == "todo", "an answer puts the job back in the queue with the answer in its context")
        # the 85% stop and ask: claude at 86 after a run
        r = js("run", FAKE_PCT="86")
        check(r["state"] == "done", "a run that ends past the reserve still finishes")
        t = js("tick")
        check(t["ran"] == [] and any("Keep crew going" in q for q in t["asked"]), "at the reserve the tick runs nothing and asks once to continue")
        check(js("tick")["asked"] == [], "the ask is filed once, not every tick")
        key = [x["key"] for x in json.loads(run("list"))["questions"] if x["key"].startswith("continue-claude")][0]
        run("answer", key, "yes")
        n = js("next")
        check(n["next"] is not None and n["runner"] == "claude", "after a yes, crew continues past the reserve")
        # the conservative fallback: no reading at all
        shutil.rmtree(codex_home)
        os.remove(os.path.join(home, "crew", "usage.json"))
        u = js("usage", MSTACK_CREW_NO_PROBE="1")
        check(u["claude"]["mode"] == "conservative" and "cannot be read" in u["claude"]["why"], "no reading means conservative mode, said plainly")
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        check(n["next"] is None and all("small cap" in w for w in n["waiting"].values()), "conservative mode has a small daily cap (3 jobs ran today)")
        state_path = os.path.join(home, "crew", "state.json")
        st0 = json.load(open(state_path))
        json.dump(dict(st0, daily={}), open(state_path, "w"))
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        check(n["next"] is not None, "conservative mode still runs in quiet hours, under the cap")
        with open(os.path.join(home, "crew", "config.json"), "w") as fh:
            json.dump(dict(cfg, quiet_hours={"start": "03:00", "end": "03:01"}), fh)
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        check(n["next"] is None and all("quiet hours" in w for w in n["waiting"].values()), "outside quiet hours a conservative runner waits")
        with open(os.path.join(home, "crew", "config.json"), "w") as fh:
            json.dump(cfg, fh)
        # no two jobs on the same files
        run("add", "proj", "Edit shared.py for A", "--file", "shared.py")
        run("add", "proj", "Edit shared.py for B", "--file", "shared.py")
        q = json.load(open(os.path.join(home, "crew", "queue.json")))
        a = next(j for j in q["jobs"] if j["title"].endswith("for A"))
        st = {"paused": False, "running": [{"job": a["id"], "pid": os.getpid()}], "daily": {}, "digest_sent": ""}
        json.dump(st, open(os.path.join(home, "crew", "state.json"), "w"))
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        b = next(j for j in q["jobs"] if j["title"].endswith("for B"))
        check(n["waiting"].get(b["id"], "").startswith("another job is running"), "a job on the same files waits while the other runs")
        json.dump(dict(st, running=[]), open(os.path.join(home, "crew", "state.json"), "w"))
        # chrome: inferred needs, the lock, and two projects at once
        chrome_j = js("add", "proj", "Run full tests", "--tier", "small",
                      "--done", "all pass::python3 tests/run_all.py", "--outcome", "report only")
        check(chrome_j["job"].get("needs") == ["chrome"], "a done check that names run_all gets needs chrome")
        eval_job = next(j for j in json.loads(run("list", "--all"))["jobs"] if j["source"].startswith("evaluator"))
        q_full = json.load(open(os.path.join(home, "crew", "queue.json")))
        check((next(j for j in q_full["jobs"] if j["id"] == eval_job["id"]).get("needs") or []) == ["chrome"],
              "evaluator source jobs always need chrome")
        lock_dir = os.path.join(home, "locks")
        os.makedirs(lock_dir, exist_ok=True)
        with open(os.path.join(lock_dir, "chrome.json"), "w") as fh:
            json.dump({"owner": "multi-evaluator review", "pid": os.getpid(), "since": "2026-11-07T10:00:00"}, fh)
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        why = n["waiting"].get(chrome_j["job"]["id"], "")
        check(why.startswith("waiting for chrome") and "multi-evaluator review" in why,
              "next waits for chrome and names the lock holder")
        with open(os.path.join(lock_dir, "chrome.json"), "w") as fh:
            json.dump({"owner": "gone", "pid": 999999999, "since": "2026-11-07T09:00:00"}, fh)
        n = js("next", MSTACK_CREW_NO_PROBE="1")
        check(not n["waiting"].get(chrome_j["job"]["id"], "").startswith("waiting for chrome"),
              "a stale chrome lock does not block the job")
        stale_lock = os.path.join(lock_dir, "chrome.json")
        if os.path.exists(stale_lock):
            os.remove(stale_lock)
        repo2 = os.path.join(work, "proj2")
        os.makedirs(repo2)
        subprocess.run(["git", "-C", repo2, "init", "-q", "-b", "main"], check=True)
        git(repo2, "add", "-A")
        subprocess.run(["git", "-C", repo2, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", "init", "--allow-empty"], check=True)
        cfg2 = json.load(open(os.path.join(home, "crew", "config.json")))
        cfg2["projects"].append({"id": "proj2", "path": repo2, "branch": "main", "stream": "other", "test": "true",
                                 "sources": []})
        json.dump(cfg2, open(os.path.join(home, "crew", "config.json"), "w"))
        qa = js("add", "proj", "Chrome job A", "--tier", "small", "--done", "x::python3 tests/run_all.py")["job"]["id"]
        qb = js("add", "proj2", "Chrome job B", "--tier", "small", "--done", "x::python3 tests/run_all.py")["job"]["id"]
        with open(os.path.join(lock_dir, "chrome.json"), "w") as fh:
            json.dump({"owner": "multi-evaluator review", "pid": os.getpid(), "since": "2026-11-07T10:00:00"}, fh)
        t = js("tick", "--max", "2", MSTACK_CREW_NO_PROBE="1")
        ran_chrome = [r["job"] for r in t["ran"] if r["job"] in (qa, qb)]
        check(len(ran_chrome) == 0, "two chrome jobs on different projects do not run while chrome is held")
        os.remove(os.path.join(lock_dir, "chrome.json"))
        if LOCKS not in sys.path:
            sys.path.insert(0, LOCKS)
        import locks as mstack_locks
        os.environ["MSTACK_HOME"] = home
        mstack_locks.write_lock("chrome", "crew test holder", os.getpid())
        review = os.path.join(work, "mini-review")
        os.makedirs(os.path.join(review, "rounds", "r1", "briefs"))
        with open(os.path.join(review, "mstack-eval.json"), "w") as fh:
            json.dump({"name": "Mini", "about": "x", "persona": "x", "target": {"url": "http://127.0.0.1:9/", "start": ["true"]},
                       "views": [], "journeys": [{"id": 1, "name": "J", "task": "t"}],
                       "reviewers": [{"id": "fast", "kind": "command", "shared_chrome": True, "timeout_minutes": 0.05,
                                      "command": "true"}]}, fh)
        with open(os.path.join(review, "rounds", "r1", "briefs", "fast.md"), "w") as fh:
            fh.write("brief")
        rv = subprocess.run([sys.executable, LOOP, "review", "--dir", review, "--cdp-port", "19999"],
                            capture_output=True, text=True, env=dict(env, MSTACK_HOME=home), timeout=30)
        mstack_locks.release("chrome")
        check(rv.returncode != 0 and "crew test holder" in (rv.stdout + rv.stderr),
              "review with a held chrome lock prints who holds it and exits non-zero")
        # the heavy job waits for quiet hours or away
        with open(os.path.join(home, "crew", "config.json"), "w") as fh:
            json.dump(dict(cfg, quiet_hours={"start": "03:00", "end": "03:01"}), fh)
        js("usage", "--probe", FAKE_PCT="40")                         # a probe through the stand-in gives a reading again
        n = js("next")
        design = next(j for j in q["jobs"] if j["title"].startswith("Design"))
        check(n["waiting"].get(design["id"], "").startswith("heavy job"), "a top tier job waits for quiet hours or until the person is away")
        n = js("next", MSTACK_CREW_AWAY="1")
        check(design["id"] not in n["waiting"] or not n["waiting"][design["id"]].startswith("heavy job"), "when away-mode says away, heavy jobs may run")
        with open(os.path.join(home, "crew", "config.json"), "w") as fh:
            json.dump(cfg, fh)
        # the switches
        run("stop")
        check(js("tick")["stopped"].startswith("the stop file"), "the stop file stops the tick")
        run("go")
        run("pause")
        check("paused" in js("tick")["stopped"], "pause stops the tick")
        run("resume")
        with open(os.path.join(home, "config.json"), "w") as fh:
            json.dump({"disabled": ["crew"]}, fh)
        check("switched off" in js("tick")["stopped"], "mStack's off switch stops the tick")
        os.remove(os.path.join(home, "config.json"))
        # a failed done check keeps its output; a passing check writes passed output too
        fail_j = js("add", "proj", "Check fail saves output", "--done", "boom check::sh -c 'echo boom; exit 1'")["job"]
        r_fail = js("run", fail_j["id"])
        fail_path = os.path.join(home, "crew", "runs", fail_j["id"], "checks", "1-FAILED.txt")
        rel_fail = "runs/%s/checks/1-FAILED.txt" % fail_j["id"]
        check(r_fail["state"] == "blocked", "a failing done check blocks the job")
        check(os.path.isfile(fail_path) and "boom" in open(fail_path, encoding="utf-8").read(),
              "failed check output is in checks/1-FAILED.txt")
        jb_fail = next(j for j in json.loads(run("list"))["jobs"] if j["id"] == fail_j["id"])
        check(rel_fail in jb_fail["note"] and "boom check" in jb_fail["note"],
              "the job note names the check and the output file")
        pass_j = js("add", "proj", "Check pass saves output", "--done", "ok check::sh -c 'echo marker-ok'")["job"]
        r_pass = js("run", pass_j["id"])
        pass_path = os.path.join(home, "crew", "runs", pass_j["id"], "checks", "1-passed.txt")
        check(r_pass["state"] == "done", "a passing done check lets the job finish")
        check(os.path.isfile(pass_path) and "marker-ok" in open(pass_path, encoding="utf-8").read(),
              "passed check output is in checks/1-passed.txt")
        # small job with one done command: the brief says run exactly, not find files
        one_cmd = js("add", "proj", "Run the test suite", "--tier", "small", "--done",
                     "tests pass::python3 tests/run_all.py", "--outcome", "report whether tests pass, change nothing")
        p_path = one_cmd["job"]["id"]
        dr = js("run", p_path, "--dry-run")
        prompt_text = open(dr["prompt"], encoding="utf-8").read()
        check("Run exactly:" in prompt_text and "python3 tests/run_all.py" in prompt_text,
              "a small one-command dry run brief names the command verbatim")
        check("find the few files" not in prompt_text,
              "a small one-command dry run brief does not tell the runner to find files")
        named = js("add", "proj", "Edit the plan", "--tier", "small", "--file", "docs/PLAN.md", "--outcome", "fix typo")
        dr2 = js("run", named["job"]["id"], "--dry-run")
        prompt2 = open(dr2["prompt"], encoding="utf-8").read()
        check("docs/PLAN.md" in prompt2 and "Files for this job" in prompt2,
              "a small job with files named still lists those files in the brief")
        # digest marks a small job that used more than 200k tokens as heavy for its tier
        q_path = os.path.join(home, "crew", "queue.json")
        q_heavy = json.load(open(q_path))
        scripts = os.path.join(ROOT, "skills", "crew", "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import crew_digest as dg
        import crew_store as cst
        heavy_j = cst.new_job("proj", "Token heavy small job", tier="small", done=["x::true"])
        heavy_j.update(state="done", finished=cst.stamp(), usage={"total_tokens": 250000}, evidence=["ok"], title=heavy_j["title"])
        q_heavy["jobs"].append(heavy_j)
        json.dump(q_heavy, open(q_path, "w"))
        html_heavy = dg.build_html(dg.gather(cfg, q_heavy))
        check("heavy for its tier" in html_heavy, "the digest marks a small job over 200k tokens as heavy for its tier")
        # the digest
        d = js("digest", "--no-send")
        html = open(d["html"]).read()
        check(rel_fail in html, "the digest shows the path to the failed check output")
        check(os.path.exists(d["html"]) and "Finished, with evidence" in html and "Waiting for you" in html and "Usage against the cap" in html,
              "the digest has what finished, what waits and the usage")
        check("stand-in finished" not in html or "commit" in html, "finished jobs show their commits")
        check(d["north_star"]["outcomes_without_the_person"] >= 2 and d["north_star"]["tokens_per_outcome"] > 0, "the north star numbers are there")
        # install: the dry run writes nothing
        before = sorted(os.listdir(agents))
        text = run("install", "--dry-run")
        check("DRY RUN" in text and ("com.mstack.crew" in text or "mstack-crew" in text), "the install dry run shows exactly what it would write")
        check(sorted(os.listdir(agents)) == before and not os.path.exists(os.path.join(home, "crew", "tick.log")), "the dry run writes nothing")
        if sys.platform == "darwin":
            r = js("install", "--every", "20")
            check(os.path.exists(os.path.join(agents, "com.mstack.crew.plist")) and "StartInterval" in open(os.path.join(agents, "com.mstack.crew.plist")).read(),
                  "install writes the launchd agent into the (stand-in) LaunchAgents folder")
            check(js("status")["installed"] is True, "status knows it is installed")
            js("uninstall")
            check(not os.path.exists(os.path.join(agents, "com.mstack.crew.plist")), "uninstall removes it")
        s = js("status")
        check(isinstance(s["next_step"], str) and s["jobs"]["done"] >= 2, "status says where crew stands and what to do next")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
