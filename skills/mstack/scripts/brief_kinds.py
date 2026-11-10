"""The text that is particular to each kind of brief. brief.py puts it in the shared frame.

Plain functions that return lines, so brief.py stays short. Standard library only.
"""

KINDS = ("tester", "reviewer", "worker", "research", "security")

ROLE = {"tester": "tester", "reviewer": "reviewer", "worker": "worker", "research": "researcher",
        "security": "security checker"}

ONE_LINE = {
    "tester": "plays a named person using the real thing and reports what happened, with a release or hold gate",
    "reviewer": "scores the journeys blind, in the same reply format multi-evaluator's reviewers use",
    "worker": "does a coding job, tests first, in a side branch or its own worktree",
    "research": "reads only, answers in a paragraph, and tags every claim verified or unconfirmed",
    "security": "checks a repository for leaked secrets and unchecked input, and changes nothing",
}


def tester(opts):
    lines = ["Walk the product as a person would, using the real thing.", ""]
    if opts.get("persona_line"):
        lines += ["Play this person (from the rules file):", "- " + opts["persona_line"], ""]
    lines += ["Test this: %s" % opts["target"]]
    if opts.get("target_lines"):
        lines += ["", "Test targets from the rules file:"] + ["- " + x for x in opts["target_lines"]]
    lines += ["", "Rules of the walk:",
              "- Use a fresh, one-use session. Do not reuse a login, cookie or state from an earlier walk.",
              "- Look only. Do not change any data unless the goal above says to.",
              "- For every finding, quote the exact words you saw on screen.",
              "- Give every finding a number and a severity: Blocker (the person cannot finish, or a safety or "
              "trust rule is broken), Major, Minor or Nit.",
              "- Say what you could not test, and why."]
    if opts.get("previous"):
        lines += ["", "Earlier report: %s" % opts["previous"],
                  "Before any new finding, re-grade every numbered finding in that file as Done, Partly, Not or "
                  "Regressed, with the words you saw on screen for each."]
    return lines


def tester_finish():
    return ["Reply with a short report: the findings by number (re-grades first when there is an earlier report), "
            "then what could not be tested. End the report with a gate line that is exactly `RELEASE` or `HOLD`, "
            "then the reason in one sentence. The gate is HOLD whenever a Blocker is open."]


def reviewer(opts):
    lines = ["You are a blind reviewer in fresh context. You have not seen any scores or previous verdicts, and you "
             "must not look for them: do not open earlier reports, verdict files or score tables."]
    if opts.get("target"):
        lines += ["", "Review this: %s" % opts["target"]]
    if opts.get("persona_line"):
        lines += ["", "Judge it as this person would (from the rules file):", "- " + opts["persona_line"]]
    lines += ["", "Score the journeys the goal names, driving the real thing, the way multi-evaluator's reviewers do."]
    return lines


def reviewer_finish(verdict_path):
    return ["Reply in the format in %s, and follow it exactly. In short:" % verdict_path,
            "- Score every journey 0 to 10, and give each an `if_fixed` score (never below the score).",
            "- Give each fix a severity (blocker, high, medium or low) and the exact place it is.",
            "- List what you could not test in `could_not_test`."]


def worker(opts):
    if opts.get("worktree"):
        where = ["Work only in this folder: %s" % opts["worktree"], "Your branch is %s." % opts["branch"]]
    else:
        where = ["Work in %s, in a side branch you make, and name it when you finish." % opts["project"]]
    return where + ["", "Worker rules:",
                    "- Tests first: add or change the test, see it fail, then make it pass.",
                    "- Change named files only. If you need another file, say so and why.",
                    "- Do not commit unless the goal above says to. Never push.",
                    "- Keep secrets and private paths out of files, commits and your reply."]


def worker_finish():
    return ["Reply with the files you changed, the test you added, and the last lines of the final test output."]


def research(opts):
    return ["Read only. Change nothing: no files, no settings, no accounts.", "",
            "Tag every claim VERIFIED or UNCONFIRMED. A VERIFIED claim names its source: the file and line, the "
            "address, or the command output. Anything you did not see yourself is UNCONFIRMED. Name every source."]


def research_finish():
    return ["Reply with a one paragraph answer first, then the evidence: each claim, its tag and its source."]


def security(opts):
    return ["Check this repository. You change nothing.", "", "Look for:",
            "- Secrets ever committed, on any branch. Report where, by file and commit, never the value.",
            "- Untrusted input that reaches a shell, a file path or a network call without a check.",
            "- Anything that changes accounts or sends anything.",
            "- What the tests do not cover."]


def security_finish():
    return ["Reply with a table of findings (severity, and the exact file and line), then the fixes in order. "
            "Never print a secret's value anywhere in the reply."]
