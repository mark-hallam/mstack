#!/usr/bin/env python3
"""What a crew job's agent may run to check its own work: the project's exact check commands and nothing wider.

The worker never holds the keys to its own checks. The crew runs every done check itself when the agent
stops, so a check the agent cannot run is not a blocker. A rule for a whole program (for example everything
that starts with python3) would let an unattended agent run anything, so only the exact command is allowed,
and a command that chains or redirects (a shell operator) is not allowed at all.
"""

SHELL_OPERATORS = ("&&", "||", ";", "|", "&", ">", "<", "`", "$(", "\n", "\r")


def exact_command(cmd):
    """The command as one exact string, or "" when it is empty or holds a shell operator."""
    cmd = (cmd or "").strip()
    if not cmd or any(op in cmd for op in SHELL_OPERATORS):
        return ""
    return cmd


def agent_commands(p, job=None):
    """The exact check commands from the project's test and done lists (and this job's own done checks, the
    same commands the crew runs itself afterwards) that the agent may run."""
    seen, out = set(), []
    for raw in [p.get("test")] + [d.partition("::")[2] for d in p.get("done", []) + ((job or {}).get("done") or [])]:
        cmd = exact_command(raw)
        if cmd and cmd not in seen:
            seen.add(cmd)
            out.append(cmd)
    return out


def tool_rules(p, job=None):
    """Claude Code permission rules: Bash(<the full command>) matches that command only (a trailing :* would
    match every command that starts with it)."""
    return ["Bash(%s)" % c for c in agent_commands(p, job)]


def job_check_commands(job):
    return [d.partition("::")[2].strip() for d in job.get("done", []) if d.partition("::")[2].strip()]


def prompt_lines(p, job):
    """The job brief's lines about which commands the agent may run, and that the crew re-runs every check."""
    allowed = agent_commands(p, job)
    lines = ["", "Commands you may run to check your work (exactly these, nothing wider):"]
    lines += ["- `%s`" % c for c in allowed] or ["- none: the crew runs the checks"]
    cannot = [c for c in job_check_commands(job) if c not in allowed]
    if cannot:
        lines.append("You cannot run these checks yourself: " + "; ".join("`%s`" % c for c in cannot) + ".")
    lines.append("The crew runs every done check again itself when you finish, so a check you cannot run is not a "
                 "blocker: make the change, report what you did, and stop.")
    return lines
