# mStack, for agents

This file is for AI coding agents (Codex, Cursor, Claude Code, Gemini, Copilot and others) working in or
with this repository. People should start with README.md.

mStack is a collection of skills. Each skill is a folder in `skills/` with a `SKILL.md` (the instructions,
written so any agent can follow them) and `scripts/` (standard library tools that do the work). No skill
needs a package install or an account.

## The skills switch on by themselves

The person never has to name a skill. When a skill's moment comes, read its `SKILL.md` and follow it.

| Skill | Switches on when | Start here |
|---|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. On by default: notify them without being asked. | `skills/ping-me/SKILL.md` |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch with defaults, run to a verified outcome. | `skills/outcome-first/SKILL.md` |
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). | `skills/multi-evaluator/SKILL.md` |
| design-direction | Someone wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from. Up to four whole directions, a comparison page, the person's pick, structure-only variants, a locked brand file. | `skills/design-direction/SKILL.md` |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back. Notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). On by default. | `skills/away-mode/SKILL.md` |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for (a queue across projects, the cheapest fitting model, their 15% of every usage window kept, drafts and side branches only, a morning digest), or asks what the crew finished or what their usage is. | `skills/crew/SKILL.md` |
| mstack | The person switches a skill off or on, asks to "review my skills", or an mStack skill finishes (record how it went). | `skills/mstack/SKILL.md` |

Before using any of them: if `~/.mstack/config.json` lists the skill under `"disabled"`, or the person said
not to use it for this task, do not. If `~/.mstack/learned/<skill>.md` exists, read it: it holds the
person's accepted improvements and wins over the skill's own file.

## Using a skill from any agent

1. Read the skill's `SKILL.md` in full and follow it. Where it names a Claude Code tool (the Agent tool,
   PushNotification, AskUserQuestion), use your own equivalent.
2. Run its tools with `python3` (and `node` for multi-evaluator) from the skill's `scripts/` folder. They all
   accept `--json` and say what to do next.
3. Ask the person before anything that costs money, sends anything, or changes their settings files.
4. To make the skills switch on by themselves in every session of your agent:
   `python3 skills/mstack/scripts/mstack.py routing` prints a block for your global instructions, and
   `setup codex` or `setup cursor` writes it after the person says yes.

## Working on this repository

- Python 3.9 or later and Node.js 18 or later, standard library only. No dependencies.
- Run every test before every commit: `python3 tests/run_all.py`. The multi-evaluator self-test needs
  Google Chrome or Chromium.
- Writing style for every file: plain English, Australian spelling, no dashes used as punctuation, and none of
  the hype words listed in `tests/style_scan.py`.
- No personal data, private paths, email addresses or tokens in any file; `tests/leak_scan.py` checks.
- A new skill goes in `skills/<name>/` with a `SKILL.md` that has `name` and `description` frontmatter and
  the "Before you start (every mStack skill)" section, plus a row in the table above, in the mstack index
  skill, in README.md and in `docs/agents.md`. `tests/test_skills.py` checks all of that.
