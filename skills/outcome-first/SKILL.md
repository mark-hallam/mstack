---
name: outcome-first
description: For any task bigger than a few steps, pin down the outcome and what done looks like, ask every question in one batch with defaults, then run to a verified outcome without needing the person again. The path of least resistance for the person: front-load everything before starting work. Pin down the outcome they want and what done looks like, ask every relevant question in one batch with sensible defaults, then run to that outcome on your own, in parallel where possible, with a durable progress file that survives restarts and a self-scheduled resume if a usage limit is reached. Stops only when the outcome is achieved and verified with evidence, then reports once. Use when the person gives a goal, project or multi-step task, says "just get it done", "handle it", "I'll be away", "take care of this", or when work would otherwise need them to keep checking in.
---

# Outcome first

The person says what they want once. You ask everything you need once. Then you carry it all the way to a
verified outcome without needing them again, unless a decision is genuinely theirs or an action only they
can take. Then you report once.

The tool is `scripts/outcome.py` (next to this file). Below, `OUTCOME` means
`python3 <this skill's folder>/scripts/outcome.py`. Every command takes `--json`.

## Before you start (every mStack skill)

- If `~/.mstack/config.json` lists `outcome-first` under `"disabled"`, or the person said not to use it for
  this task, work the usual way.
- If `~/.mstack/learned/outcome-first.md` exists, read it: it holds this person's accepted improvements,
  and they win over this file.
- If the task is small (a question, one edit, a few steps), just do it. This skill is for real work.

## 1. Pin the outcome

Write one sentence: the outcome the person wants, in their terms ("The site is live at example.com with
the new pricing page, and the checkout works"). Then list what **done** looks like, each item something
you can prove: a test that passes, an address that loads, a file that exists, a screenshot, a number.
Where a command can prove it, note the command.

## 2. Ask everything in one batch

Think through the whole task first: every choice, credential, preference, permission and unknown you
will hit. Then ask them all **at once**, each with a sensible default, so the person can reply "go" to
accept every default.

- Claude Code: one AskUserQuestion call with up to four questions; put the rest in the same message as a
  numbered list with defaults.
- Other agents: one message, a numbered list, each with "(default: ...)".
- Always include: "Is this what done looks like?", and "May I run unattended until it is done, including
  scheduling my own resume if a usage limit stops me? (default: yes)".

Do not start the work until the person has answered or said "go".

## 3. Set up the durable plan

```
OUTCOME new "<the outcome>" --cwd <project folder> \
  --done "Tests pass::npm test" --done "The pricing page loads::curl -fsS https://example.com/pricing" \
  --done "The person can see the new page" \
  --resume-command "<how to start a new session that continues, see step 6>"
OUTCOME task add <slug> "Write the pricing page"
OUTCOME task add <slug> "Add checkout tests"
OUTCOME task add <slug> "Deploy" --after t1,t2
```

This writes `~/.mstack/outcomes/<slug>/progress.md`, the one file anyone (you after a restart, another
session, another agent, the person) reads to know exactly where things stand. Keep it current: mark tasks
as you go, and add notes with `OUTCOME note`.

## 4. Run, in parallel

- `OUTCOME ready <slug>` lists every task that can start now. Start them **at the same time**: one subagent
  each (Claude Code: the Agent tool), or separate sessions where your platform allows, each with a short,
  complete brief. Do small tasks yourself.
- When a task finishes, mark it with its evidence: `OUTCOME task set <slug> t1 --state done --evidence "..."`.
  A task without evidence is not done.
- If you hit a decision that is genuinely the person's, or an action only they can take, queue it with
  `OUTCOME ask <slug> "<question>" --default "<your suggestion>"`, carry on with everything else, and ask
  all queued questions in one batch only when nothing else can move. Ping them when you do (the ping-me
  skill).
- Everything else, decide yourself, sensibly, and note why.

## 5. Verify, then report once

`OUTCOME check <slug>` runs every done check that has a command and records the result as evidence. For a
check with no command, look for yourself and record what you saw: `OUTCOME verify <slug> d3 --evidence "..."`.
The outcome is achieved only when every task is done and every check passed with evidence, never on your
own say-so.

Then report **once**: the outcome, the evidence for each done check, and anything left for the person. Ping
them (the ping-me skill).

## 6. If a usage limit stops you

Before your session ends, make sure `progress.md` is current, then schedule your own resume:

- **Claude Code**: use its scheduling (a scheduled wakeup or task) to resume after the limit resets, with
  the prompt "Resume the mStack outcome <slug>: read its progress.md and continue".
- **Codex**: `codex exec resume --last "Resume the mStack outcome <slug>: read its progress.md and continue"`
  is a good `--resume-command`.
- **Anywhere else**, or as a fallback: `OUTCOME schedule <slug> --in-minutes 300` (or `--at "YYYY-MM-DD HH:MM"`)
  adds a one-off line to the computer's crontab that runs the saved resume command and then removes itself.
  `--dry-run` shows the line first. Only with the person's yes from step 2.

When you come back, read `progress.md` (or `OUTCOME status --json`) and continue from the next step.

## After

Record privately how it went, for the person's own improvements:
`python3 <mstack skill folder>/scripts/mstack.py log outcome-first --outcome reached|partial|not-reached --needed-user "..." --stalled "..."`
(the mstack skill sits next to this one).
