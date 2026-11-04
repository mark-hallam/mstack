#!/usr/bin/env python3
"""Self-test for crew's side branches: a project that already has a branch named plain "crew" (git will not let
crew/<id> sit beside it) gets crew-jobs/<id> instead, and the worker rules no longer ask the worker to commit,
because the crew saves the work itself and a sandboxed worker often cannot write to git.

Everything runs in a throwaway folder and a throwaway git repository.

  python3 tests/test_crew_branch.py
"""
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
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
