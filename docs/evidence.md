# Numbers, with where they come from

Every number mStack's README gives is measured, dated, and traceable to a file. The files that hold
private data (review folders of a real product, logs with folder paths) stay on the author's computer;
what is public is the method and the result. Where a number is not public, this page says so.

## 7 November 2026: a clean install, on a Mac that had never seen mStack

- A separate, empty Claude Code profile and an empty mStack home were used, so none of the author's own
  rules or memory could help.
- Install from GitHub: two commands, succeeded first time (version 0.4.1).
- Six plain phrases a stranger might type, each in a fresh headless session, asked only which installed
  skill it would use. **Six of six picked the right skill**: "I'm heading out, run the tests and let me know"
  (outcome-first, with ping-me and away-mode noted), "keep improving my landing page until it's ready to show
  real customers" (multi-evaluator), "I'm on my phone now, show me the report" (away-mode), "big job, don't
  keep asking me questions one at a time" (outcome-first), "keep working through my projects while I'm not
  around" (crew), "what skills do I have and when do they switch on?" (mstack).
- Cursor, given only the rules block that `mstack.py routing` prints, routed two of the same phrases
  correctly with Grok 4.7.
- Not tested that day: Codex (its usage was used up at the time).
- Rerun the same evening on the 0.5.0 release candidate, installed from the local repository into a fresh
  profile: five of six picked the same skill. The "I'm heading out, run the tests and let me know" phrase went
  to crew instead of outcome-first, which is defensible (both run work while the person is away, and ping-me
  is always on). Recorded as it happened.

- Rerun at about 23:15 on the released 0.6.0, installed from GitHub into a fresh profile, with two new phrases for
  the sixth skill ("I'm starting a new app and have no idea what it should look like yet. Show me a few directions so
  I can pick one" and "Keep the look we already have, but try two or three different layouts for the home screen and
  let me choose"): **eight of eight picked the right skill**, both new ones design-direction, and the "heading out,
  run the tests" phrase went to ping-me, which is the expected pair with outcome-first.

## 7 November 2026: one review round with three AI makers

A real product (the author's own app) was reviewed in round 5 of an existing multi-evaluator loop, with
Claude (Anthropic), Codex (OpenAI) and Grok (xAI, through the Cursor command line) each driving the app
in a real headless browser, in fresh context, blind to each other and to earlier rounds.

- **All three found the same bug independently**: a "tailor to a role" feature marked a requirement as
  backed by evidence on the strength of a line the product itself labelled as the person's own word.
  Two of the three also found a second one (a confirmation sheet promising one thing and the page then
  showing another).
- Overall scores: Claude 8.7, Codex 8.3, Grok 6. The reviewers disagreed by 2 to 4 points on every
  journey, so the round was not ready, and the report said so.
- **The noise check worked.** Each reviewer also scores a frozen set of screens every round. Claude's
  control score was 6 in all five rounds; Codex's was 6, 8, 8, 8 across four rounds; Grok's first was 4.
  A change smaller than a reviewer's own control movement is reported as within noise, not as progress.
- The round also caught a mistake by the person running it: the change note said nothing had changed
  since the previous round, and two reviewers' comparison passes showed otherwise. That is now checked by
  the tool (the product's commit is recorded at capture).

The verdicts and screenshots are in the author's private review folder for that product; the round's
scores and the three "broken" lists are quoted here exactly.

## 7 November 2026: one crew job, watched end to end

- Crew read usage first: the author's Claude window was at 91%, past the 85% reserve, so crew refused to
  use it and chose Codex (at 75%).
- The job ran in its own worktree on a side branch, changed no files, and ended with a result block
  saying "done".
- Crew then ran the job's done check itself. It failed (a Chrome clash with a review running on the same
  Mac at that moment), so crew marked the job blocked instead of trusting the runner. Run alone a few
  minutes later, the same check passed.
- Nothing was pushed. That clash is why 0.5 treats Chrome as a shared resource with a lock.

## What is not claimed

- No speed, cost or quality improvement figures. None have been measured properly yet.
- No user counts. There are none to report.
- "I use them every day" refers to the author, on his own projects, since 4 November 2026.
