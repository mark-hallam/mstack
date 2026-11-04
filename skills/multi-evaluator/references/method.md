# The method, and why it works this way

## The loop

1. **Journeys and criteria first.** Write the journeys a real person must complete, end to end, and the
   criteria each is scored on. Start with six: clear, quick, trust, familiar, calm, works everywhere.
2. **The same screens, captured the same way, every round.** Light theme first, desktop and phone, so
   before and after compare like for like.
3. **At least two independent reviewers from different AI makers** (for example a Claude reviewer and a
   Codex reviewer), each in fresh context, driving the real product in a real browser, never told the
   expected answer. Each scores every journey 0 to 10, gives an "if fixed" score, and proposes specific
   fixes with a severity.
4. **A report every round**: one self-contained HTML page with the score trend toward 10, each journey
   now against last round and if fixed, what changed, what the reviewers propose, before and after
   screenshots per screen, and a filmstrip of every round.
5. **Fix, then repeat** until every reviewer gives every journey 10. Then test with real people: where
   they disagree with the AI reviewers, the real people win. AI scores are a strong signal, not proof.
6. **Tell the person** when a round needs them: the light theme screenshots, the report, and a phone
   notification.

## Why two makers

Reviewers from the same maker tend to share blind spots and taste. Two from different makers disagree
in useful ways: one notices a broken counter, the other notices the phone layout. Where they agree, the
fix is almost certainly right. Where only one raises something, look at it yourself before acting.

## Why fresh context and no expected answer

A reviewer who has seen the plan, the last scores or the other reviewer's verdict anchors on them. The
brief gives only what a first-time user would know, plus the screens from last round to compare.

## Why "if fixed"

The gap between a journey's score and its "if fixed" score says how much the proposed fixes are worth. A
journey at 6 with an "if fixed" of 9 is the best place to spend the next round.

## The criteria grow with the product

The floor is where every product starts. As scores rise, each stage adds criteria, so the bar keeps rising
and a 10 keeps meaning something. A journey only counts as 10 when it meets every criterion in force for
that round, and the report shows which criteria each round used.

- **Stage 1, the first minutes**: time to value (a first-time user gets real value quickly, measured step
  by step), error recovery (every failure ends in one plain sentence and one way forward), copy (plain
  English, no jargon, every number explained where it appears).
- **Stage 2, once the main features exist**: agent experience (an AI agent completes every journey through
  the product's command line or connector alone, with the same results and refusals as a person), a trust
  audit (every claim traceable to its source in one tap), accessibility measured (contrast and keyboard
  checks pass, screen reader labels complete, 200 percent text works, reduced motion respected), speed
  (screens draw in under a second, actions answer in under half a second).
- **Stage 3, before real users**: the five-second test, emotional tone, consistency, data safety (nothing
  lost on a refresh or a crash; every change can be undone or is logged), delight.
- **Stage 4, real people**: five first-time users complete the journeys unaided; their time, stumbles and
  words are recorded and compared with the AI scores. Where they disagree, the people win.

## When to stop

When every reviewer gives every journey 10 under every criterion in force, and real people agree. If the
reviewers plateau below 10 for two rounds, look at whether the journeys or criteria ask for something the
product should not do, and talk to the person before changing them.
