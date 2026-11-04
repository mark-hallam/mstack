# Changelog

Every release of mStack, newest first. Dates are the day the release was made.

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
