---
name: mstack
description: mStack's always-on index. Lists every mStack skill and when each switches on by itself, so the person never has to name one. Use at the start of any substantial task to see which mStack skills apply; when the person says to switch an mStack skill off or on, or "don't use <skill>" for a task; when they ask to "review my skills", improve a skill, or see what a skill has learned; after any mStack skill finishes, to record privately how it went; and to set mStack up in Codex, Cursor or Claude Code hooks.
---

# mStack

mStack is a set of skills for people and their AI agents. Installing mStack (or any one of its skills)
makes all of them available, and each switches on by itself when its moment comes. The person never has
to call one by name.

The shared tool is `scripts/mstack.py` (next to this file). Below, `MSTACK` means
`python3 <this skill's folder>/scripts/mstack.py`.

## The skills, and when each switches on

| Skill | Switches on when | Default |
|---|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. | On |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch, then run to a verified outcome without further input. | On |
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds until every journey scores 10 out of 10 from independent AI reviewers. | On |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back: notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). | On |

`MSTACK skills` prints the same list with each skill's state. Read a skill's `SKILL.md` when it switches on.

## Switching skills off

- For good: `MSTACK disable <skill>` (and `enable <skill>`). This writes `~/.mstack/config.json`:
  `{"disabled": ["ping-me"]}`. The person can also edit that file by hand.
- For one task: if the person says "don't use <skill>" (or "no pings", "just do it", and so on), do not use
  it for that task. No file changes.
- Every mStack skill checks the config before it starts. `MSTACK enabled <skill>` exits 0 when it is on.

**The off switch is that one file and nothing else.** Switching a skill off, for good or for a task, never
edits CLAUDE.md, AGENTS.md, `.cursor/rules`, `settings.json`, `config.toml` or any other instructions or
settings file, and never works around `MSTACK_HOME` (if it is set, that is the home to use; never unset it
to reach the person's real `~/.mstack`). If the person wants a rule written into their own instructions
file, they write it, or they ask for exactly that and see the change first.

## Getting better, privately

Each skill learns from how it is used, on this computer only. Nothing leaves the machine unless the person
chooses to share an improvement.

1. **After every use** of an mStack skill, record how it went in one line:
   `MSTACK log <skill> --outcome reached|partial|not-reached --needed-user "<where it needed the person>" --stalled "<where it stalled>" --correction "<what the person corrected>"`
   (each flag can repeat; leave out what did not happen). It goes to `~/.mstack/journal/<skill>.jsonl`.
2. **"Review my skills"** (when the person asks, or once when the session start note says a review is due):
   - `MSTACK review --json` gathers the journal since the last review into evidence per skill.
   - For each skill with new uses, read its `SKILL.md` and the evidence, and propose concrete edits: a rule
     to add ("Ask about the deploy target in the first batch of questions") or a change to the skill's
     wording. One line each, with the evidence behind it.
   - Show them to the person in one batch. Keep only what they accept: `MSTACK learn <skill> "<rule>"`.
     Accepted rules live in `~/.mstack/learned/<skill>.md`, survive mStack updates, and win over the
     skill's own file.
3. **Sharing an improvement** is the person's choice: `MSTACK learned <skill>` prints what was learned, and
   they can open an issue or pull request on github.com/mark-hallam/mstack with it if they want to.

## Setting mStack up in each agent

- **Claude Code**: install the plugin (`/plugin marketplace add mark-hallam/mstack`, then
  `/plugin install mstack@mstack`). Its session start hook adds the always-on rules to every session.
- **Codex**: `MSTACK setup codex` shows what it would add (mStack's routing block in `~/.codex/AGENTS.md`,
  and ping-me's `notify` line in `~/.codex/config.toml`). Ask the person, then run it again with `--write`.
- **Cursor**: `MSTACK setup cursor --project <folder>` shows an always-applied rule for that project. Ask,
  then `--write`.
- **Any other agent**: `MSTACK routing` prints the block to paste into its instructions, or point it at
  https://github.com/mark-hallam/mstack/blob/main/docs/agents.md.

Never change the person's settings files without showing them the change and getting a yes.
