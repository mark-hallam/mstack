# mStack, for agents

This file is for AI coding agents (Codex, Cursor, Claude Code, Gemini, Copilot and others) working in or
with this repository. People should start with README.md.

mStack is a collection of skills. Each skill is a folder in `skills/` with a `SKILL.md` (the instructions,
written so any agent can follow them), `scripts/` (standard library tools that do the work) and
`references/` (detail to read when needed). No skill needs a package install or an account with mStack.

## Skills

| Skill | Use it when | Start here |
|---|---|---|
| multi-evaluator | Someone wants a site, app or document reviewed and improved in rounds until every user journey scores 10 out of 10 from independent AI reviewers made by different companies, with before and after screenshots and an HTML report. | `skills/multi-evaluator/SKILL.md` |

## Using a skill from any agent

1. Read the skill's `SKILL.md` in full and follow it. Where it names a Claude Code tool (for example the
   Agent tool for a fresh-context reviewer), use your own equivalent: a new session, thread or subagent
   with only the brief as its instructions.
2. Run its tools with `python3` and `node` from the skill's `scripts/` folder. Every multi-evaluator
   command accepts `--json`, and `eval_loop.py status --json` always says what to do next.
3. Ask the person before anything that costs money, sends anything, or changes their product's design
   direction. Show them the report and screenshots at the end of each round.

## Working on this repository

- Python 3.9 or later and Node.js 18 or later, standard library only. No dependencies.
- Run the tests before every commit: `python3 tests/leak_scan.py && python3 tests/selftest.py`.
  The self-test needs Google Chrome or Chromium and runs three review rounds on a tiny local page with
  stand-in reviewers (no AI, no network beyond this computer).
- Writing style for every file: plain English, Australian spelling, no dashes used as punctuation, and none of
  the hype words listed in `tests/leak_scan.py`.
- No personal data, private paths, email addresses or tokens in any file; `tests/leak_scan.py` checks.
- A new skill goes in `skills/<name>/` with a `SKILL.md` that has `name` and `description` frontmatter, and
  a row in the table above, in README.md and in `docs/agents.md`.
