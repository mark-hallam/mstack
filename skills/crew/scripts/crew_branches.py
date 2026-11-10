#!/usr/bin/env python3
"""The side branches crew leaves in a project's repository (crew/<job id>, or crew-jobs/<job id>): list them with
their job and how far ahead they are, and prune the ones that hold nothing the person still needs.

A branch is only ever deleted when it is fully merged into the project's default branch (or has no commits
ahead), is not checked out in any worktree, and does not belong to a running job. A branch with unmerged
commits is listed with the commands to merge or delete it, never deleted.
"""
import shlex
import subprocess

PREFIXES = ("crew/", "crew-jobs/")


def _run(path, *args):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout.strip()


def default_branch(p):
    """The branch the crew works from: the project's "branch", else what is checked out in the project folder."""
    base = p.get("branch") or _run(p["path"], "rev-parse", "--abbrev-ref", "HEAD")[1]
    if base and _run(p["path"], "rev-parse", "--verify", "--quiet", "refs/heads/" + base)[0] == 0:
        return base
    return ""


def crew_branches(path):
    code, out = _run(path, "for-each-ref", "--format=%(refname:short)", "refs/heads/crew", "refs/heads/crew-jobs")
    return [b for b in out.splitlines() if b.startswith(PREFIXES)] if code == 0 else []


def checked_out(path):
    code, out = _run(path, "worktree", "list", "--porcelain")
    return set(l[len("branch refs/heads/"):] for l in out.splitlines() if l.startswith("branch refs/heads/")) if code == 0 else set()


def ahead(path, base, branch):
    code, out = _run(path, "rev-list", "--count", "%s..%s" % (base, branch))
    return int(out) if code == 0 and out.isdigit() else 0


def is_merged(path, base, branch):
    return _run(path, "merge-base", "--is-ancestor", branch, base)[0] == 0


def has_own_commits(p, branch):
    """True when the branch holds commits that are not on the project's base branch (or when that cannot be told)."""
    base = default_branch(p)
    if not base:
        return True
    return ahead(p["path"], base, branch) > 0 and not is_merged(p["path"], base, branch)


def job_id_of(branch):
    return branch.split("/", 1)[1]


def project_rows(p, q, state):
    path = p["path"]
    base = default_branch(p)
    running = set(r["job"] for r in (state or {}).get("running", []))
    jobs = dict((j["id"], j) for j in q.get("jobs", []))
    live = set(j for j, v in jobs.items() if v.get("state") == "doing")
    out = {"project": p["id"], "path": path, "default": base, "branches": [], "note": ""}
    if not base:
        out["note"] = "not a git repository, or its branch %r does not exist" % p.get("branch", "")
        return out
    wts = checked_out(path)
    for b in crew_branches(path):
        jid = job_id_of(b)
        n, merged = ahead(path, base, b), is_merged(path, base, b)
        row = {"branch": b, "job": jid, "status": (jobs.get(jid) or {}).get("state", "unknown"), "ahead": n,
               "merged": merged, "checked_out": b in wts, "running": jid in running or jid in live}
        row["prunable"] = (merged or n == 0) and not row["checked_out"] and not row["running"]
        if not merged and n > 0:
            row["merge_command"] = "git -C %s switch %s && git -C %s merge %s" % (
                shlex.quote(path), shlex.quote(base), shlex.quote(path), shlex.quote(b))
            row["delete_command"] = "git -C %s branch -D %s" % (shlex.quote(path), shlex.quote(b))
        out["branches"].append(row)
    return out


def report(cfg, q, state, project=None, prune=False):
    """Every project's crew branches. With prune, deletes the safe ones and lists the unmerged ones with commands."""
    projects = [p for p in cfg["projects"] if not project or p["id"] == project]
    res = {"ok": True, "pruned": [], "unmerged": [], "projects": []}
    for p in projects:
        rows = project_rows(p, q, state)
        if prune:
            for row in rows["branches"]:
                if row["prunable"]:
                    _run(p["path"], "branch", "-D", row["branch"])
                    res["pruned"].append(row["branch"])
                    row["pruned"] = True
        for row in rows["branches"]:
            if not row["merged"] and row["ahead"] > 0:
                res["unmerged"].append(dict(row, project=p["id"]))
        res["projects"].append(rows)
    return res


def unmerged_count(cfg, q, state):
    try:
        return len(report(cfg, q, state)["unmerged"])
    except (OSError, subprocess.SubprocessError, KeyError):
        return 0


def render_text(res):
    lines = []
    for pr in res["projects"]:
        lines.append("%s (default branch %s)%s" % (pr["project"], pr["default"] or "?", ": " + pr["note"] if pr["note"] else ""))
        for r in pr["branches"]:
            state = "pruned" if r.get("pruned") else ("merged" if r["merged"] else "%d commit(s) ahead, not merged" % r["ahead"])
            lines.append("  %s  job %s (%s)  %s%s%s" % (r["branch"], r["job"], r["status"], state,
                                                        ", checked out" if r["checked_out"] else "", ", running" if r["running"] else ""))
        if not pr["branches"] and not pr["note"]:
            lines.append("  no crew branches")
    for u in res["unmerged"]:
        lines += ["", "Kept, with unmerged work: %s" % u["branch"], "  merge it:  %s" % u["merge_command"],
                  "  delete it: %s" % u["delete_command"]]
    if res["pruned"]:
        lines += ["", "Deleted %d merged or empty branch(es): %s" % (len(res["pruned"]), ", ".join(res["pruned"]))]
    return "\n".join(lines)
