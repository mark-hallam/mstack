---
name: multi-evaluator
description: Improve a product's design in rounds until it is ready for real people: every user journey scores 9 or better from independent AI reviewers made by different companies, who agree within a point, with no high-severity fix open, held for two rounds. Uses at least two reviewers (for example Claude and Codex). Each round captures the same screens the same way, each reviewer drives the real product in a real browser in fresh context and scores every journey 0 to 10 with an "if fixed" score and specific fixes, and a self-contained HTML report shows the score trend, before and after screenshots and a filmstrip of every round. Use when someone wants a site, app, profile or document reviewed and improved autonomously, asks for independent UX or design reviews, a design review loop, multiple evaluators, before and after screenshots, or "keep improving it until it is 10 out of 10" (the loop stops at ready for people, not at a unanimous 10).
---

# Multi-evaluator design improvement loop

Rounds of independent review until the product is **ready for people**: every journey scores 9 or better
from every reviewer, no high-severity fix is open, the reviewers agree within a point, and that has held
for two rounds in a row. A unanimous 10 is a flag to double check the brief, not the goal. AI scores are
a strong signal, not proof: when the loop says ready, real first-time people test it, and where they
disagree with the AI, the people win.

Everything runs through one command line tool, `scripts/eval_loop.py` (next to this file), so a person,
this agent, or any other agent gets the same results. Every command takes `--dir <review folder>`, and
`status --json` always says where the loop is and what to do next. Needs Python 3.9 or later, Node.js 18
or later and Google Chrome or Chromium. Nothing else to install.

Below, `LOOP` means `python3 <this skill's folder>/scripts/eval_loop.py`.

## Before you start (every mStack skill)

- If `~/.mstack/config.json` lists `multi-evaluator` under `"disabled"`, or the person said not to use it
  for this task, work the usual way.
- If `~/.mstack/learned/multi-evaluator.md` exists, read it: it holds this person's accepted improvements,
  and they win over this file.
- When the loop ends (or stops), record privately how it went:
  `python3 <mstack skill folder>/scripts/mstack.py log multi-evaluator --outcome reached|partial|not-reached --needed-user "..." --stalled "..."`
  (the mstack skill sits next to this one).

## 1. Journeys and criteria first

Before any review, agree with the person what a real person must be able to do, end to end.

1. `LOOP init --dir design-review --name "<product>" --start "<command that starts it, with {port}>" --cwd <its folder>`
   (or `--url <address>` for something already running, such as a staging site).
2. Fill in `design-review/mstack-eval.json` with the person. See `references/config.md` for every field:
   - `about` and `persona`: what the product is and who judges it. Keep the design direction and any
     constraints out of `about` and in `rules`: they are shown to reviewers as "not scored", so the brief
     never hands over the answer you hope to hear.
   - `journeys`: 3 to 6 real tasks, each end to end ("Add a book and see it in the list").
   - `views`: the fixed screens captured every round (desktop, phone, dark theme). Light theme first.
   - `criteria`: the floor is clear, quick, trust, familiar, calm, works everywhere. `stages` add more
     criteria as the product matures (time to value, error recovery, copy, agent experience, measured
     accessibility, speed, five-second test, emotional tone, consistency, data safety, delight). Turn a
     stage on with `"active": true` or `"from_round": <n>` when the scores show the floor is met.
   - `reviewers`: at least two, from different AI makers. The default is Claude (run by you, the agent)
     and Codex (run by the tool with `codex exec`).
3. Show the person the journeys and criteria and get a yes before round 1.

## 2. Each round

```
LOOP start-round --dir design-review          # opens rounds/r<N>/, snapshots this round's criteria
                                              # write rounds/r<N>/changes.md: what changed, one bullet each
LOOP capture --dir design-review              # the same screens, captured the same way, every round
LOOP brief --dir design-review                # blind scoring briefs in rounds/r<N>/briefs/, plus -compare briefs from round 2
LOOP review --dir design-review               # runs command line reviewers (Codex) in parallel; run it in the background
```

At the same time, run every reviewer whose `kind` is `agent` yourself, in **fresh context**:

- Claude Code: start a subagent (the Agent tool, general purpose) whose prompt is the full text of
  `rounds/r<N>/briefs/claude.md`. Do not add your own opinions, the expected answer or earlier scores.
- Any other agent: open a new session or thread with the brief as the only instruction.

When it replies, save its JSON (the tool checks it and refuses a reply that does not fit the format):

```
LOOP verdict --dir design-review --reviewer claude reply.json      # or pipe the reply in with -
```

**Blind first, compare second.** The scoring brief shows this round only: no earlier screenshots, no
earlier scores, no design direction, so the score means the same thing in round 1 and round 9. From round
2 there is also `rounds/r<N>/briefs/<reviewer>-compare.md`. Give it to the same reviewer **after** its
verdict is saved (the same session is fine; it is no longer blind), and save the reply apart from the
score:

```
LOOP verdict --dir design-review --reviewer claude --compare compare-reply.json
LOOP report --dir design-review                                     # writes design-review/report.html
```

The comparison never changes a score; the report shows it under "What changed".

Then show the person the report and the light theme screenshots (`rounds/r<N>/shots/`). Send them a
notification if your agent can (in Claude Code, PushNotification) when a round's report is ready or the
loop needs a decision; the config's `notify` command can also send one (see `references/config.md`).

## 3. Fix, then repeat

1. Merge both reviewers' fixes: high severity first, then anything both reviewers raised.
2. Make the fixes in the product, run its own tests, and write the next round's `changes.md`.
3. `LOOP start-round`, and repeat until `LOOP status` says **ready for people** (the stopping rule above,
   held for two rounds). If a round passes, change nothing big and run one more so it holds. After
   `max_rounds` (default 6) without reaching it, `status` says to stop and talk to the person: the journeys
   or criteria may be asking for something the product should not do.
4. Then real people: five first-time users try the journeys unaided. Record their time, stumbles and words
   in `rounds/r<N>/people.md` (one bullet each; the report shows them). Where they disagree with the AI
   reviewers, the people win: turn what they found into journeys or criteria for the next round.

## Rules

- Reviewers never see each other's verdicts, earlier rounds, earlier scores or the report while scoring;
  the brief tells them so. Comparison with last round is a separate pass, after the verdict.
- The same views, captured the same way, every round, so before and after compare like for like.
- Never let a reviewer submit real payments, messages or personal data. Use demo data and a fresh copy.
- Sandboxed reviewers (Codex) cannot start Chrome: `review` starts a shared headless Chrome and the brief
  tells them to put `MSTACK_CDP_PORT=<port>` in front of the driver command.
- If a reviewer's reply does not fit, read `rounds/r<N>/work/<reviewer>/raw-reply.txt`, then rerun it. The
  tool refuses a 10 that still proposes fixes, and an "if fixed" below the score.
- Keep the review folder in the product's repository (or next to it) so every round is kept.

## Files

- `scripts/eval_loop.py`: the command line tool (init, status, start-round, capture, brief, serve, review,
  verdict, validate, report, notify).
- `scripts/drive.mjs`: the journey driver, a real headless Chrome; reviewers use it directly.
- `scripts/report.py`: the report builder. `scripts/readiness.py`: the stopping rule and the noise check.
- `templates/mstack-eval.json`: the starter config.
- `references/config.md`: every config field. `references/verdict-format.md`: the reply format.
  `references/method.md`: why the loop works this way and how the criteria grow.
