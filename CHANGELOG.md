# Changelog

Every release of mStack, newest first. Dates are the day the release was made.

## Unreleased

## Unreleased

- outcome-first: a question budget. `questions` shows at most `max_questions` (default 6, set in `~/.mstack/config.json`), the rest are taken by default, and replying "defaults" accepts them all.
- mstack: a rules file per project (`mstack rules init|show|list|import|accept`) kept in the mStack home, never in a repository; crew, multi-evaluator and design-direction briefs and the session start note all read it.

## 0.6.0, 7 November 2026

- multi-evaluator: every capture now measures each view (length, repeated phrases, contrast, alt text, sideways scroll,
  reduce motion, page weight, heading skips) and the report shows the numbers round by round under "Measured".
- multi-evaluator: the compare pass re-grades last round's numbered fixes (done, partly, not, regressed, not
  testable, with the exact words seen), there is a new "blocker" severity that caps a journey at 5 and stops a
  round being ready, journeys can name a persona, and replies can list what could not be tested.
- New skill, design-direction: finds the look of a new product (a brief with hard rules, up to four whole working directions, a comparison page with a recommendation, the person's pick, structure-only variants with numbered questions, a locked brand file). multi-evaluator's config can name that brand file so its briefs list the brand rules.

## 0.5.0, 7 November 2026

- multi-evaluator: the real-people step after "ready for people" is optional wording now; the stopping rule
  itself is unchanged.
- The public face: the README opens with the four jobs you do not need to be in, a one-line promise,
  proof that the skills switch on by themselves, a 30-second install, and measured numbers with their sources
  (docs/evidence.md). New docs/comparison.md says how mStack sits beside the popular skill stacks.
- crew: a job that fails a check, gets no result block, or whose runner exits non zero is retried automatically
  up to three times (never when the runner asked a question), then parked; each attempt is kept under
  `runs/<job-id>/attempt-<n>/`.
- crew: jobs declare shared resources such as `chrome`; crew and multi-evaluator review take a lock under
  `~/.mstack/locks` so a done check that runs the full test suite does not clash with a review on the same Mac.
- multi-evaluator: command line reviewers can use Cursor's agent with a `{home}` placeholder; every saved
  verdict records `maker` and `model`, the report header shows them, and reviewers with `"enabled": false`
  are skipped by brief, review and readiness. `eval_loop.py` and `report.py` are split into smaller modules.
- multi-evaluator: each reviewer's brief now gets a port nothing on the computer already holds, so two
  reviews running on one computer (or a leftover server) no longer hand out the same port. The self-test
  checks the port it was given, not a fixed one.
- multi-evaluator: the journey driver's select step finds an option by its value or its visible text, fires
  the input and change events a real choice fires, and says NOT FOUND with the options when nothing matches,
  instead of silently clearing the choice.
- crew: a small job with one done check and no files named now briefs the runner to run that command
  only, instead of searching the repository. The digest marks such a job as heavy for its tier when it
  uses more than 200,000 tokens.
- crew: when a job's done check fails, the check output is saved under the run folder and the blocked note
  and digest name the file so you do not have to run the check again.
- multi-evaluator: capture records the product git commit in each round's views.json; status and the report
  show it, warn when changes.md says nothing changed but the build moved, and note when two clean rounds
  share the same commit.
- multi-evaluator: readiness, status and the report judge each round by the reviewers that round had briefs
  for, not today's config alone, so a reviewer added later is not treated as missing from earlier rounds.

## 0.4.1, 5 November 2026

- away-mode: screenshots and PDFs now really render in the light theme. Headless Chrome ignored the old
  colour scheme switch, so a computer set to dark mode got dark screenshots; it now uses the setting Chrome
  actually honours.
- crew: workers no longer try to save their own work to git. A sandboxed worker often cannot, and jobs it had
  finished came back marked blocked. The crew already saves the changes on the job's side branch itself, and
  the worker's rules now say so.
- crew: a project that already has a branch named plain `crew` no longer blocks every job from starting (git
  will not let `crew/<job>` sit beside it). Those projects get `crew-jobs/<job>` instead.

## 0.4.0, 5 November 2026

- away-mode: phone screenshots are now laid out at true phone width (390 css px). Headless Chrome will not lay a page out narrower than about 500 px, so earlier phone screenshots lost their right edge.

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
