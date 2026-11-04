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

Do not start the work until the person has answered or said "go", **unless nobody can answer**: a headless
run (`claude -p`, `codex exec`, a scheduled job) has no way to ask, and a person who said "just handle it,
I'll be away" has already answered. Then take every default, write them into the progress file so they are
visible (`OUTCOME answer <slug> --defaults`, after queueing the questions with `OUTCOME ask`), say so in
the report, and carry on. Never invent an answer that has no default: queue it and leave it open.

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

**This step is not optional.** Work done under this skill without a progress file is not following it:
there is no evidence trail, nothing to resume from, and no way for the person to see where things stand.
Create the outcome before the first task starts, even for a run that asks no questions.

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
The outcome is achieved only when every task is done, every check passed with evidence, and no question
for the person is still open (`check` refuses otherwise: answer it, or take the defaults), never on your
own say-so.

Then report **once**: the outcome, the evidence for each done check, and anything left for the person. Ping
them (the ping-me skill).

## 6. If a usage limit stops you (what works, plainly)

A usage limit stops you mid-turn, before you can schedule anything, and **Claude Code has no built-in
after-the-limit resume**: its wakeup tool is a loop timer capped at one hour, not a scheduler. So the only
resume that works is one armed **in advance**, from the computer's own scheduler, with a command that runs
unattended. Set it up right after step 3, with the person's yes from step 2, and remove it when done:

```
OUTCOME schedule <slug> --in-minutes 330      # a one-off crontab line; --dry-run shows it first
OUTCOME unschedule <slug>                     # when the outcome is achieved (resume also removes it)
```

The line carries this session's PATH and `MSTACK_HOME`, runs the saved `--resume-command` in the project
folder, logs to `~/.mstack/outcomes/<slug>/resume.log`, and deletes itself so it never runs twice. The tool
refuses a resume command whose program it cannot find on the PATH now, because cron could not find it
later either. Resume commands that run unattended:

- **Codex**: `codex exec resume --last "Resume the mStack outcome <slug>: read its progress.md and continue"`.
- **Claude Code**: `claude -p "Resume the mStack outcome <slug>: read its progress.md and continue"` with
  whatever permission flags the person accepts for unattended work. Without them it waits for a yes
  nobody is there to give.
- Try the command once by hand before relying on it. If nothing can run unattended on this computer, say
  so in `progress.md` and in your report, and ask the person to start a new session when the limit resets.

Before your session ends for any reason, make sure `progress.md` is current: it is the only thing the
next session reads. When you come back, read it (or `OUTCOME status --json`) and continue from the next
step.

## After

Record privately how it went, for the person's own improvements:
`python3 <mstack skill folder>/scripts/mstack.py log outcome-first --outcome reached|partial|not-reached --needed-user "..." --stalled "..."`
(the mstack skill sits next to this one).
