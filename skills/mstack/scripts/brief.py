#!/usr/bin/env python3
"""One line from the person becomes a complete brief for another agent, and can start it on a runner.

  brief <tester|reviewer|worker|research|security> "<one line goal>" [--project F] [--read FILE ...]
        [--persona ID] [--target ADDRESS_OR_APP] [--previous REPORT] [--worktree] [--unattended]
        [--run RUNNER] [--model NAME] [--json]

The brief is written to <home>/briefs/<date>-<kind>-<slug>.md ($MSTACK_HOME or ~/.mstack) and printed. It always
carries the project's rules (rules.py) and the finishing block crew uses. Python 3.9 or later, standard library only.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import brief_kinds as kinds  # noqa: E402
import rules as rules_file  # noqa: E402

VERDICT = os.path.join(SKILLS, "multi-evaluator", "references", "verdict-format.md")
BUILTIN_RUNNERS = {"claude": {"command": ["claude", "-p"]}, "codex": {"command": ["codex", "exec"]},
                   "cursor": {"command": ["cursor-agent", "-p"]}}
TIMEOUT = 1800


def die(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:6]) or "brief"


def finish_block():
    crew = os.path.join(SKILLS, "crew", "scripts")
    if crew not in sys.path:
        sys.path.insert(0, crew)
    from crew_run import FINISH
    return FINISH


# ---------------------------------------------------------------- the pieces

def read_list(project, extra):
    files = []
    for f in extra:
        if not os.path.exists(f):
            die("The file to read does not exist: %s" % f)
        files.append(os.path.abspath(f))
    for name in ("HANDOFF.md", "README.md"):
        p = os.path.join(project, name)
        if os.path.isfile(p) and p not in files:
            files.append(p)
    return files


def personas(lines):
    out = {}
    for x in lines:
        m = re.match(r"persona\s+([^:\s]+)\s*:", x)
        if m:
            out[m.group(1)] = x
    return out


def make_worktree(project, slug):
    git = ["git", "-C", project]
    if subprocess.run(git + ["rev-parse", "--git-dir"], capture_output=True).returncode != 0:
        die("%s is not a git repository, so a worktree cannot be made." % project)
    if subprocess.run(git + ["rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode != 0:
        die("%s has no commits yet, so a worktree cannot be made." % project)
    branch = "work/" + slug
    if subprocess.run(git + ["rev-parse", "--verify", "-q", "refs/heads/" + branch], capture_output=True).returncode == 0:
        die("The branch %s already exists. Pick a different goal, or remove that branch and worktree first." % branch)
    path = os.path.join(os.path.dirname(project), os.path.basename(project) + "-wt", slug)
    if os.path.exists(path):
        die("The folder %s already exists." % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run(git + ["worktree", "add", "-b", branch, path], capture_output=True, text=True)
    if r.returncode != 0:
        die("Could not make the worktree: %s" % (r.stderr.strip() or r.stdout.strip()))
    return path, branch


def compose(args, project, rules_paths, reads, persona_line, target_lines, worktree, branch):
    name = os.path.basename(project.rstrip(os.sep)) or "project"
    out = ["# %s: %s" % (args.kind.capitalize(), args.goal), "",
           "You are the %s for %s." % (kinds.ROLE[args.kind], name), "", "## Read these first", ""]
    out += ["- " + f for f in reads] or ["- (no HANDOFF.md or README.md in %s)" % project]
    out += ["", "Read nothing else unless these point to it.", "", "## Rules", ""]
    block = rules_file.block(project)
    if block:
        out.append(block)
    else:
        out.append("No rules file yet for this project (python3 %s init --project %s writes one)." % (
            os.path.join(HERE, "rules.py"), project))
    if args.unattended:
        out += ["", "Ask nothing. Take the default on every choice and say which defaults you took."]
    opts = {"target": args.target, "persona_line": persona_line, "target_lines": target_lines,
            "previous": os.path.abspath(args.previous) if args.previous else "", "worktree": worktree,
            "branch": branch, "project": project}
    job = getattr(kinds, args.kind)(opts)
    if args.kind in ("security", "research", "worker") and args.target:
        job = ["Target: %s" % args.target, ""] + job
    fin = {"tester": kinds.tester_finish, "worker": kinds.worker_finish, "research": kinds.research_finish,
           "security": kinds.security_finish}
    finish = kinds.reviewer_finish(VERDICT) if args.kind == "reviewer" else fin[args.kind]()
    out += ["", "## Your job", "", "Goal: %s" % args.goal, ""] + job
    out += ["", "## How to finish", ""] + finish + ["", finish_block()]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- running it

def runner_table(home):
    table = {k: dict(v) for k, v in BUILTIN_RUNNERS.items()}
    try:
        with open(os.path.join(home, "crew", "config.json"), encoding="utf-8") as fh:
            for k, v in (json.load(fh).get("runners") or {}).items():
                if isinstance(v, dict) and v.get("command"):
                    table[k] = v
    except (OSError, ValueError, AttributeError):
        pass
    extra = os.environ.get("MSTACK_BRIEF_RUNNERS_JSON")
    if extra:
        try:
            table.update(json.loads(extra))
        except ValueError:
            die("MSTACK_BRIEF_RUNNERS_JSON is not valid JSON.")
    return table


def run_command(entry, name, model, text):
    cmd = list(entry.get("command") or [name])
    if model:
        cmd += ["--model", model]
    cmd += list(entry.get("extra_args") or [])
    if name == "claude":
        return cmd, text
    return cmd + [text], None


def start(args, brief_path, text, home):
    entry = runner_table(home).get(args.run)
    if not entry:
        die("No runner called %s. Known runners: %s. The brief is at %s" % (
            args.run, ", ".join(sorted(runner_table(home))), brief_path))
    cmd, stdin = run_command(entry, args.run, args.model, text)
    if not shutil.which(cmd[0]):
        die("The runner command %s is not on PATH, so nothing was started. The brief is at %s" % (cmd[0], brief_path))
    reply = brief_path[:-3] + ".reply.md"
    try:
        r = subprocess.run(cmd, input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        die("The runner %s did not finish in 30 minutes. The brief is at %s" % (args.run, brief_path))
    except OSError as e:
        die("The runner %s could not start (%s). The brief is at %s" % (args.run, e, brief_path))
    with open(reply, "w", encoding="utf-8") as fh:
        fh.write(r.stdout)
    return {"runner": args.run, "model": args.model or None, "exit_code": r.returncode, "reply": reply}


# ---------------------------------------------------------------- main

def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(prog=prog, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=kinds.KINDS)
    ap.add_argument("goal", help="the goal, in one line")
    ap.add_argument("--project", help="the project folder (default: here)")
    ap.add_argument("--read", action="append", default=[], help="a file to read first (repeat for more)")
    ap.add_argument("--persona", help="tester or reviewer: a persona id from the rules file's Test targets")
    ap.add_argument("--target", help="the address or app to test or review (required for tester)")
    ap.add_argument("--previous", help="tester: an earlier report to re-grade first")
    ap.add_argument("--worktree", action="store_true", help="worker: make a git worktree and branch for the job")
    ap.add_argument("--unattended", action="store_true", help="the agent asks nothing and takes the defaults")
    ap.add_argument("--run", help="start the brief on a runner (claude, codex, cursor, or one from the crew config)")
    ap.add_argument("--model", help="the model name to pass to the runner")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    project = os.path.realpath(args.project or os.getcwd())
    if not os.path.isdir(project):
        die("The project folder does not exist: %s" % project)
    if args.kind == "tester" and not args.target:
        die("A tester brief needs --target (the address or app to test).")
    if args.previous and not os.path.isfile(args.previous):
        die("The earlier report does not exist: %s" % args.previous)
    reads = read_list(project, args.read)
    m = rules_file.merged(project)
    target_lines = m["rules"].get("Test targets", [])
    persona_line = ""
    if args.persona:
        found = personas(target_lines)
        if args.persona not in found:
            die("No persona called %s in the rules file. Personas found: %s" % (
                args.persona, ", ".join(sorted(found)) or "none"))
        persona_line = found[args.persona]
    slug = slugify(args.goal)
    worktree, branch = "", ""
    if args.kind == "worker" and args.worktree:
        worktree, branch = make_worktree(project, slug)
    text = compose(args, project, m["paths"], reads, persona_line, target_lines, worktree, branch)
    home = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    os.makedirs(os.path.join(home, "briefs"), exist_ok=True)
    path = os.path.join(home, "briefs", "%s-%s-%s.md" % (
        datetime.datetime.now().strftime("%Y-%m-%d-%H%M"), args.kind, slug))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    ran = start(args, path, text, home) if args.run else None
    data = {"path": path, "kind": args.kind, "project": project, "rules_from": m["paths"],
            "worktree": worktree or None, "run": ran}
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print(text)
    print("Brief written to %s" % path)
    if ran:
        print("Reply saved to %s (runner %s, exit code %d)" % (ran["reply"], ran["runner"], ran["exit_code"]))


if __name__ == "__main__":
    main()
