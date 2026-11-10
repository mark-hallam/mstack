#!/usr/bin/env python3
"""Self-test for crew's side branches: a project that already has a branch named plain "crew" (git will not let
crew/<id> sit beside it) gets crew-jobs/<id> instead, and the worker rules no longer ask the worker to commit,
because the crew saves the work itself and a sandboxed worker often cannot write to git.

Everything runs in a throwaway folder and a throwaway git repository.

  python3 tests/test_crew_branch.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@localhost"] + list(args),
                   check=True, capture_output=True)


def new_repo(work, name="project"):
    repo = os.path.join(work, name)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "first")
    return repo


def commit_on(repo, branch, name):
    git(repo, "checkout", "-q", branch)
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work " + name)
    git(repo, "checkout", "-q", "main")


def branch_exists(repo, name):
    return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + name],
                          capture_output=True).returncode == 0


def test_exact_commands():
    import crew_run
    p = {"id": "x", "path": "/nowhere", "test": "python3 tests/run_all.py",
         "done": ["lint::make lint && make test", "ok::python3 tests/leak_scan.py"], "allowed_tools": ["Bash(ls:*)"]}
    tools = crew_run.allowed_tools(p)
    check("Bash(python3 tests/run_all.py)" in tools, "the test command is allowed as the exact command")
    check(not any(t.startswith("Bash(python3:") for t in tools), "no rule lets the agent run any python3 program")
    check(not any(t.endswith(":*)") and "run_all" in t for t in tools), "an exact rule has no :* ending")
    check("Bash(python3 tests/leak_scan.py)" in tools, "a plain done command is allowed exactly")
    check(not any("make" in t for t in tools), "a done command with && adds nothing")
    check("Bash(ls:*)" in tools, "the person's own allowed_tools list is kept as written")
    for bad in ("a | b", "a > f", "a < f", "a; b", "a || b", "echo `x`", "echo $(x)", "a\nb"):
        check(crew_run.perms.exact_command(bad) == "", "a command with a shell operator is not allowed: %r" % bad)
    job = {"id": "j", "outcome": "do it", "done": ["tests pass::python3 tests/run_all.py", "lint::make lint && make test"],
           "tier": "fast", "files": ["a.py"]}
    prompt = crew_run.build_prompt({}, p, job, "/w", "crew/j")
    check("python3 tests/run_all.py" in prompt and "runs every done check again itself" in prompt,
          "the prompt names the exact command and says the crew runs every check again")
    check("make lint && make test" in prompt and "cannot run" in prompt, "the prompt says which check the agent cannot run itself")
    cmd = crew_run.runner_command({"runners": {"claude": {"command": ["claude", "-p"]}}}, "claude", p,
                                  {"tier": "fast"}, "/w", "PROMPT")
    check("--allowedTools" in cmd and "Bash(python3 tests/run_all.py)" in cmd, "the Claude command line carries the exact rule")


def test_branches_and_finish(work):
    import crew_branches as cb
    import crew_run
    repo = new_repo(work, "bproj")
    cfg = {"projects": [{"id": "bp", "path": repo, "branch": "main", "mode": "branch"}]}
    for b in ("crew/empty-1", "crew/merged-1", "crew/work-1", "crew/busy-1", "crew/run-1"):
        git(repo, "branch", b)
    commit_on(repo, "crew/merged-1", "m.txt")
    git(repo, "merge", "-q", "--no-edit", "crew/merged-1")
    commit_on(repo, "crew/work-1", "w.txt")
    commit_on(repo, "crew/busy-1", "b.txt")
    commit_on(repo, "crew/run-1", "r.txt")
    wt = os.path.join(work, "wt-busy")
    git(repo, "worktree", "add", wt, "crew/busy-1")
    q = {"jobs": [{"id": "work-1", "project": "bp", "state": "blocked"}, {"id": "run-1", "project": "bp", "state": "doing"},
                  {"id": "merged-1", "project": "bp", "state": "done"}], "questions": []}
    state = {"running": [{"job": "run-1", "pid": 1, "started": ""}]}
    rep = cb.report(cfg, q, state)
    rows = dict((b["branch"], b) for b in rep["projects"][0]["branches"])
    check(set(rows) == {"crew/empty-1", "crew/merged-1", "crew/work-1", "crew/busy-1", "crew/run-1"}, "branches lists every crew branch")
    check(rows["crew/work-1"]["ahead"] == 1 and rows["crew/work-1"]["merged"] is False and rows["crew/work-1"]["status"] == "blocked",
          "a row has the job status, commits ahead and merged or not")
    check(rows["crew/merged-1"]["merged"] is True and rows["crew/empty-1"]["ahead"] == 0, "merged and empty branches are marked")
    before = sorted(b for b in rows)
    check(rep["pruned"] == [] and branch_exists(repo, "crew/empty-1"), "a plain listing deletes nothing")
    rep = cb.report(cfg, q, state, prune=True)
    check(sorted(rep["pruned"]) == ["crew/empty-1", "crew/merged-1"], "prune deletes only merged or empty branches: %s" % rep["pruned"])
    check(not branch_exists(repo, "crew/empty-1") and not branch_exists(repo, "crew/merged-1"), "those two are gone")
    check(all(branch_exists(repo, b) for b in ("crew/work-1", "crew/busy-1", "crew/run-1")), "unmerged branches stay")
    un = dict((u["branch"], u) for u in rep["unmerged"])
    check("merge" in un["crew/work-1"]["merge_command"] and "branch -D crew/work-1" in un["crew/work-1"]["delete_command"],
          "an unmerged branch is listed with the commands to merge or delete it")
    # a running job's and a checked out empty branch are not pruned
    git(repo, "branch", "crew/idle-run")
    git(repo, "branch", "crew/idle-wt")
    wt2 = os.path.join(work, "wt-idle")
    git(repo, "worktree", "add", wt2, "crew/idle-wt")
    q["jobs"].append({"id": "idle-run", "project": "bp", "state": "doing"})
    rep = cb.report(cfg, q, state, prune=True)
    check(rep["pruned"] == [] and branch_exists(repo, "crew/idle-run") and branch_exists(repo, "crew/idle-wt"),
          "a running job's branch and a branch checked out in a worktree are never pruned")
    check(cb.unmerged_count(cfg, q, state) == 3, "the digest count is the unmerged branches")
    # finish_workspace
    p = cfg["projects"][0]
    git(repo, "branch", "crew/fin-empty")
    git(repo, "branch", "crew/fin-work")
    commit_on(repo, "crew/fin-work", "f.txt")
    for b, keep in (("crew/fin-empty", False), ("crew/fin-work", True)):
        d = os.path.join(work, "wt-" + b.split("/")[1])
        git(repo, "worktree", "add", d, b)
        crew_run.finish_workspace(p, d, b, keep_branch=keep)
    check(not branch_exists(repo, "crew/fin-empty"), "a finished job with no commits ahead has its branch removed")
    check(branch_exists(repo, "crew/fin-work"), "a finished job with commits keeps its branch")
    git(repo, "branch", "crew/fin-guard")
    commit_on(repo, "crew/fin-guard", "g.txt")
    d = os.path.join(work, "wt-guard")
    git(repo, "worktree", "add", d, "crew/fin-guard")
    crew_run.finish_workspace(p, d, "crew/fin-guard", keep_branch=False)
    check(branch_exists(repo, "crew/fin-guard"), "a branch that really has commits is kept even if the caller missed them")
    # the command line, with --json, and the JSON error
    home = os.path.join(work, "cli-home")
    os.makedirs(os.path.join(home, "crew"))
    with open(os.path.join(home, "crew", "config.json"), "w") as fh:
        json.dump(cfg, fh)
    env = dict(os.environ, MSTACK_HOME=home)
    tool = os.path.join(ROOT, "skills", "crew", "scripts", "crew.py")
    r = subprocess.run([sys.executable, tool, "branches", "--json"], capture_output=True, text=True, env=env)
    data = json.loads(r.stdout)
    check(r.returncode == 0 and data["projects"][0]["project"] == "bp", "crew.py branches --json lists the branches")
    r = subprocess.run([sys.executable, tool, "branches", "--project", "nope", "--json"], capture_output=True, text=True, env=env)
    check(r.returncode != 0 and json.loads(r.stdout).get("ok") is False, "an unknown project is a JSON error with a non-zero exit")
    # the digest line
    import crew_digest
    d = {"date": "2026-01-01", "finished": [], "waiting": [], "stuck": [], "todo": [], "tokens": 0, "budgets": {},
         "north_star": {"outcomes_without_the_person": 0, "tokens_per_outcome": 0}, "branches": 3}
    check("3 unmerged crew branches" in crew_digest.build_html(d) and "crew.py branches" in crew_digest.build_html(d),
          "the digest has one line about unmerged crew branches and the command")
    d["branches"] = 0
    check("unmerged crew branch" not in crew_digest.build_html(d), "and no line when there are none")


def test_label_per_home(work):
    import hashlib
    import crew_install as ci
    saved = dict((k, os.environ.get(k)) for k in ("HOME", "MSTACK_HOME", "MSTACK_LAUNCH_AGENTS"))
    fake_home = os.path.join(work, "fakehome")
    os.makedirs(fake_home)
    try:
        os.environ["HOME"] = fake_home
        os.environ.pop("MSTACK_LAUNCH_AGENTS", None)
        os.environ.pop("MSTACK_HOME", None)
        check(ci.label() == "com.mstack.crew", "the default home keeps com.mstack.crew")
        other = os.path.join(work, "other-home")
        os.environ["MSTACK_HOME"] = other
        want = "com.mstack.crew." + hashlib.sha256(os.path.abspath(other).encode("utf-8")).hexdigest()[:8]
        check(ci.label() == want, "another home gets the label with the first 8 hex characters of its path hash")
        if sys.platform == "darwin":
            plan = ci.plan(15)
            check(plan["label"] == want and plan["writes"][0]["path"].endswith(want + ".plist")
                  and plan["writes"][0]["path"].startswith(fake_home), "install --dry-run shows the label and path it would use")
            check(ci.uninstall(True)["label"] == want, "uninstall --dry-run shows the label too")
            check(ci.installed() is False, "status says not installed when this home has no file")
            # a file for the default home does not make another home installed
            agents = os.path.join(fake_home, "Library", "LaunchAgents")
            os.makedirs(agents)
            with open(os.path.join(agents, "com.mstack.crew.plist"), "wb") as fh:
                import plistlib
                plistlib.dump({"Label": "com.mstack.crew", "EnvironmentVariables": {}}, fh)
            check(ci.installed() is False, "another home's file does not count as installed here")
            os.environ.pop("MSTACK_HOME")
            check(ci.installed() is True, "an existing default install is still seen by the default home")
            os.environ["MSTACK_HOME"] = other
            with open(os.path.join(agents, want + ".plist"), "wb") as fh:
                plistlib.dump({"Label": want, "EnvironmentVariables": {"MSTACK_HOME": os.path.join(work, "elsewhere")}}, fh)
            check(ci.installed() is False, "a file whose recorded home is a different one is not installed here")
            with open(os.path.join(agents, want + ".plist"), "wb") as fh:
                plistlib.dump({"Label": want, "EnvironmentVariables": {"MSTACK_HOME": other}}, fh)
            check(ci.installed() is True, "installed when the file exists and records this home")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    work = tempfile.mkdtemp(prefix="mstack-crew-branch-test-")
    os.environ["MSTACK_HOME"] = os.path.join(work, "home")
    sys.path.insert(0, os.path.join(ROOT, "skills", "crew", "scripts"))
    import crew_run  # noqa: E402
    try:
        repo = os.path.join(work, "project")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "first")
        check(crew_run.branch_name(repo, "p-1") == "crew/p-1", "a normal project gets crew/<id>")
        git(repo, "branch", "crew")
        check(crew_run.branch_name(repo, "p-1") == "crew-jobs/p-1", "a project with a branch named crew gets crew-jobs/<id>")
        wt, branch = crew_run.workspace({"path": repo}, {"id": "p-2"})
        check(branch == "crew-jobs/p-2" and os.path.isdir(wt), "and the worktree is made on that branch without a git error")
        check("you do not need to commit" in crew_run.RULES and "commit there with" not in crew_run.RULES,
              "the worker rules leave saving to the crew instead of asking the worker to commit")
        test_exact_commands()
        test_branches_and_finish(work)
        test_label_per_home(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
