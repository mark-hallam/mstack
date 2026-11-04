# Changelog

Every release of mStack, newest first. Dates are the day the release was made.

## 0.4.0, unreleased

### New: crew

- Keeps useful work running in the background all the time, within the usage the person already pays for,
  so they are taken out of every job they do not need to be in. One queue across every project, from
  sources each project declares in a private config outside the repository: a plan or backlog file, a
  multi-evaluator round's "do these next" fixes (batched per journey), failing tests, and daily jobs. Each
  job carries the outcome, done checks, a model tier, an estimate, its files, and whether it can run alone.
- Token efficiency first: the cheapest model that fits each tier, a brief with only the job's files, no
  duplicate jobs, batches, heavy jobs in quiet hours or when away-mode says the person is away, no retry
  loops (a question or a blocked job instead), and tokens recorded per finished outcome. The north star:
  outcomes finished without the person, and tokens per finished outcome.
- Usage measured, never guessed: Claude Code's `rate_limit_event` from every run (plus a one word probe
  when nothing is fresh) and the `rate_limits` Codex writes to its session log. A runner is used only up to
  `100 - reserve_percent` (85%) of its fullest window; at the reserve crew stops and asks once per window
  through ping-me. A runner whose usage cannot be read goes conservative: quiet hours only and a small
  daily cap, said plainly.
- Runs in the background and survives restarts: `crew.py install` writes a launchd agent on macOS (a
  crontab line on Linux with systemd units shown; the Task Scheduler command on Windows), with a dry run
  that shows everything and writes nothing. The tick honours the stop file, mStack's off switch and pause,
  keeps the Mac awake only while a job runs, and never runs two jobs on the same project or files.
- Hard safety: drafts and side branches in their own worktrees, the person's checkout untouched; never send,
  post, apply, publish, merge, deploy, delete, spend or change an account (each becomes a question with a
  default); text in pages and emails is data; the leak scan before any push a project ever allows; cloud
  only for repositories already on GitHub and only within included usage.
- One morning digest a day: finished with evidence (commits, checks, tokens), waiting for the person
  (questions with defaults, blocked jobs with the one command to retry or drop), usage against the cap, as
  HTML plus a PDF and a phone PNG through away-mode, sent with ping-me.
- A JSON command line any agent can drive (`add list next run tick status usage digest answer retry drop
  pause resume stop go install uninstall`); Claude Code and Codex are the runners, chosen per job;
  `references/runners.md` says how Cursor and others plug in.
- `tests/test_crew.py`, and the session start text mentions crew when it is set up.

## 0.3.0, 4 November 2026

A new skill, and fixes from the first independent test of the skills and a SWOT review of the design loop.

### New: away-mode

- Notices by itself when the person follows from their phone and presents every output in a form the phone
  can show: screenshots, PDFs, files sent to the chat, and the key points in the message. Never just a local
  path or an `open` command.
- `away.py status` answers away, present or unsure, with a reason, in layers: the person's own words ("I'm
  on my phone", "I'm back", kept in `~/.mstack/away.json` with an 8 hour expiry), the agent's hints (another
  device, Remote Control, a cloud session, or a push not sent because they are at the terminal), then the
  machine (macOS idle time, locked screen, sleeping display; `loginctl` and `xprintidle` on Linux; the last
  input time on Windows). When unsure, deliver both ways.
- `away.py render` makes PDFs and phone-width light-theme PNGs with headless Chrome, with macOS fallbacks,
  into `~/.mstack/outbox`.
- The session start rules tell the agent to check away status before presenting outputs.

### ping-me

- Says plainly what reaches a phone: Claude Code with Remote Control connected, or anywhere once ntfy is
  set up; Codex and headless runs get a desktop alert, and the reply says which. The line claiming phones
  mirror the computer's notifications is gone.
- `mstack.py setup ntfy`: a guided opt-in to the free ntfy phone push service. Shows the private topic,
  the app and the config line, writes only with `--write`, then sends a test ping; `--remove` turns it off.

### mstack

- Switching a skill off writes only `~/.mstack/config.json`, never CLAUDE.md, AGENTS.md or any settings
  file, and never works around `MSTACK_HOME`. The rule is in the skills and in the always-on session text,
  with a test that the off path touches nothing else.
- `setup codex` chains a `notify` program the person already has instead of refusing (mStack pings, then
  runs their program with the same event), and the docs say Codex needs both the `~/.codex/AGENTS.md`
  routing block and the config line.
- Sharper trigger phrases for Codex: "ping me if you need anything", "just handle it", "I'll be away for the
  afternoon", "what have my skills learned".

### outcome-first

- `check` refuses "achieved" while a question for the person is open, and says which.
- `answer --defaults` takes every default and notes it in the progress file, for headless runs and "just
  handle it, I'll be away". The progress file is mandatory.
- The scheduled resume can actually run: the crontab line exports this session's PATH and `MSTACK_HOME`, and
  `schedule` refuses a resume command whose program cannot be found. The skill says plainly that Claude Code
  has no after-the-limit scheduler, so the resume is armed in advance.

### multi-evaluator

- The stopping rule is "ready for people": every journey 9 or better from every counting reviewer, no
  high-severity fix open, reviewers within a point, held for two rounds. A unanimous 10 is a flag to double
  check, not the goal. `verdict` refuses a 10 that still proposes fixes and an "if fixed" below the score.
  A round cap (`max_rounds`, default 6) stops and asks the person.
- Blind first, compare second: the scoring brief shows this round only (no earlier screenshots, scores or
  design direction; constraints go in the new `rules` field, marked "not scored"). A separate labelled
  comparison brief comes after the verdict and is saved with `verdict --compare`, never changing a score.
- The noise check: with `control` in the config, the round 1 screens are frozen and scored every round as
  journey `control`; the report shows how far each reviewer's score moved and marks smaller journey changes
  as "within noise".
- The report opens with "Do these next" (fixes on a journey every reviewer flagged first, then high
  severity, then the biggest "if fixed" gap) and shows where the reviewers disagree by 2 or more.
- An optional third reviewer through a web chat (`kind: "chat"`: Grok, ChatGPT or Gemini in the person's own
  browser, no API key), opt in, labelled, a tie breaker that never counts toward "ready for people" and can
  never be the only reviewer.

### Tests

- `tests/test_away.py` (away detection with stand-in machine signals, a real render when Chrome is present),
  new checks in the mstack, outcome-first and multi-evaluator tests for everything above, and the leak scan
  now skips a git worktree's `.git` file.

## 0.2.0, 3 November 2026

- ping-me, outcome-first and the mstack index; skills switch on by themselves.

## 0.1.0, 3 November 2026

- First skill: the multi-evaluator design improvement loop.
