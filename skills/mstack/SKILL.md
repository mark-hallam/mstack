---
name: mstack
description: mStack's always-on index. Lists every mStack skill and when each switches on by itself, so the person never has to name one. Use at the start of any substantial task to see which mStack skills apply; when the person says to switch an mStack skill off or on, or "don't use <skill>" for a task; when they ask to "review my skills", "what have my skills learned", "improve a skill", "which skills do I have", or to see what an mStack skill has learned (not for creating a new skill from scratch); after any mStack skill finishes, to record privately how it went; and to set mStack up in Codex, Cursor or Claude Code hooks.
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
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). | On |
| design-direction | Someone wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from: up to four whole working directions from one brief, a comparison page with a recommendation, the person's pick, structure-only variants with numbered questions, then a locked brand file. | On |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back: notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). | On |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for: a queue across every project (plans, evaluator fixes, failing tests, daily jobs) on the cheapest fitting model, 15% of every usage window kept for them, drafts and side branches only, one morning digest. Also "what did the crew finish" and "what is my usage". | On |

`MSTACK skills` prints the same list with each skill's state. Read a skill's `SKILL.md` when it switches on.

## Switching skills off

- For good: `MSTACK disable <skill>` (and `enable <skill>`). This writes `~/.mstack/config.json`:
  `{"disabled": ["ping-me"]}`. The person can also edit that file by hand. It also holds `max_questions`
  (how many questions outcome-first asks in one batch, default 6).
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

## A rules file per project

The person should not have to retype the same rules into every brief. One rules file per project lives in the
mStack home (`~/.mstack`, or `$MSTACK_HOME`), **never in the repository**, because never-touch paths, ports and
test families are private. A global file (`~/.mstack/rules.md`) holds what applies everywhere. The project's
file (`~/.mstack/projects/<slug>/rules.md`) is found from the project folder or any folder inside it, so a
worktree finds it too. Both have the same six headings, one rule per line starting with `- `:
`## Never touch`, `## Never print`, `## Test targets`, `## Voice`, `## Working rules`, `## Done rules`.
The project's rules come first, then the global ones it did not already say. A project heading whose only rule
is `- none` drops the global rules under that heading.

- `MSTACK rules init [--global] [--project <folder>]` writes the template (it never overwrites without `--force`).
- `MSTACK rules show [--project <folder>] [--brief]` prints the merged rules; `--brief` is the block to paste
  into a brief you write for another agent. The crew, multi-evaluator and design-direction briefs add it themselves.
- `MSTACK rules import` reads the person's feedback memories and only **proposes** rules, numbered. Nothing is
  written until `MSTACK rules accept <n> ...` (only `accept` writes rules from memories).
- `MSTACK rules list` shows every known project.

Keep real secrets out of the file: a rule may name a kind of secret ("the family name"), never the secret.

## Setting mStack up in each agent

- **Claude Code**: install the plugin (`/plugin marketplace add mark-hallam/mstack`, then
  `/plugin install mstack@mstack`). Its session start hook adds the always-on rules to every session.
- **Codex**: `MSTACK setup codex` shows what it would add: mStack's routing block in `~/.codex/AGENTS.md`
  (Codex reads that file in every session; without the block the skills are visible but switch on less
  reliably) and ping-me's `notify` line in `~/.codex/config.toml`. If a `notify` program is already there,
  it is chained, not replaced: mStack pings first, then the person's own program runs with the same event;
  the original line is kept in a comment and a `.mstack-backup` copy. Ask the person, then run it again
  with `--write`. Run it again after an mStack update to refresh the block.
- **Cursor**: `MSTACK setup cursor --project <folder>` shows an always-applied rule for that project. Ask,
  then `--write`.
- **Any other agent**: `MSTACK routing` prints the block to paste into its instructions, or point it at
  https://github.com/mark-hallam/mstack/blob/main/docs/agents.md.

Never change the person's settings files without showing them the change and getting a yes.
