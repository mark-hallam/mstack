# mStack, for agents

This file is for AI coding agents (Codex, Cursor, Claude Code, Gemini, Copilot and others) working in or
with this repository. People should start with README.md.

mStack is a collection of skills. Each skill is a folder in `skills/` with a `SKILL.md` (the instructions,
written so any agent can follow them) and `scripts/` (standard library tools that do the work). No skill
needs a package install or an account.

## The skills switch on by themselves

The person never has to name a skill. When a skill's moment comes, read its `SKILL.md` and follow it.

<!-- mstack:catalog:start -->
| Skill | Switches on when | Start here |
|---|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. On by default: notify them without being asked. | `skills/ping-me/SKILL.md` |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch with defaults, then run to a verified outcome without further input. | `skills/outcome-first/SKILL.md` |
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). | `skills/multi-evaluator/SKILL.md` |
| design-direction | Someone wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from: up to four whole working directions from one brief, a comparison page with a recommendation, the person's pick, structure-only variants with numbered questions, then a locked brand file. | `skills/design-direction/SKILL.md` |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back. Notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). | `skills/away-mode/SKILL.md` |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for: a queue across every project on the cheapest fitting model, 15% of every usage window kept for them, drafts and side branches only, one morning digest. Also "what did the crew finish" and "what is my usage". | `skills/crew/SKILL.md` |
| mstack | The person asks what is happening across their projects, wants a brief for another agent or a rules file for a project, switches a skill off or on, asks to "review my skills", or an mStack skill has just finished. | `skills/mstack/SKILL.md` |

What mstack offers (`mstack.py <command>`):

- `mstack.py status`: The person asks what is happening across all their projects or what is waiting on them.
- `mstack.py brief`: The person asks for a brief for a tester, reviewer, worker, researcher or security check they are about to start.
- `mstack.py rules`: The person wants a rules file for a project, or the same rules carried into every brief.
- `mstack.py disable <skill>`: The person says to switch a skill off for good (`enable <skill>` switches it back on). For one task, just do not use it.
- `mstack.py review`: The person asks to "review my skills", what their skills have learned, or to improve a skill.
- `mstack.py log <skill>`: After any mStack skill finishes: record privately how it went.
- `mstack.py setup codex`: The person wants mStack set up in Codex, Cursor (`setup cursor`) or Claude Code hooks (`setup claude-hooks`).
<!-- mstack:catalog:end -->

Before using any of them: if `~/.mstack/config.json` lists the skill under `"disabled"`, or the person said
not to use it for this task, do not. If `~/.mstack/learned/<skill>.md` exists, read it: it holds the
person's accepted improvements and wins over the skill's own file.

## Using a skill from any agent

1. Read the skill's `SKILL.md` in full and follow it. Where it names a Claude Code tool (the Agent tool,
   PushNotification, AskUserQuestion), use your own equivalent.
2. Run its tools with `python3` from the skill's `scripts/` folder (multi-evaluator and design-direction's `shots`
   also use `node`). They all accept `--json` and say what to do next.
3. Ask the person before anything that costs money, sends anything, or changes their settings files.
4. To make the skills switch on by themselves in every session of your agent:
   `python3 skills/mstack/scripts/mstack.py session-start` (once: it makes the launcher the block uses) then
   `python3 skills/mstack/scripts/mstack.py routing` prints a block for your global instructions, and
   `setup codex` or `setup cursor` writes it after the person says yes.

## Working on this repository

- Python 3.9 or later, standard library only. Node.js 18 or later and Google Chrome or Chromium are needed only by
  multi-evaluator and design-direction's `shots` (and away-mode uses Chrome when present). No dependencies.
- Run every test before every commit: `python3 tests/run_all.py`. The multi-evaluator self-test needs
  Google Chrome or Chromium.
- Writing style for every file: plain English, Australian spelling, no dashes used as punctuation, and none of
  the hype words listed in `tests/style_scan.py`.
- No personal data, private paths, email addresses or tokens in any file; `tests/leak_scan.py` checks.
- A new skill goes in `skills/<name>/` with a `SKILL.md` that has `name` and `description` frontmatter and
  the "Before you start (every mStack skill)" section, plus an entry in `skills/mstack/catalog.json` (the one source of
  truth for the tables above and the routing block: run `mstack.py catalog --write`) and a section in README.md.
  `tests/test_skills.py` and `tests/test_catalog.py` check all of that.
