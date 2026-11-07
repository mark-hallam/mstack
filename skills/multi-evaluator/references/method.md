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
5. **Fix, then repeat** until the product is ready for people (the stopping rule below). If you can, let a
   few first-time people try it after that, and feed what they find into the next round. AI scores are a strong
   signal, not proof.
6. **Tell the person** when a round needs them: the light theme screenshots, the report, and a phone
   notification.

## Why two makers

Reviewers from the same maker tend to share blind spots and taste. Two from different makers disagree
in useful ways: one notices a broken counter, the other notices the phone layout. Where they agree, the
fix is almost certainly right. Where only one raises something, look at it yourself before acting.

## A third maker through a web chat

Heuristic evaluation practice uses three to five independent evaluators; two is the floor. A third can
come at no extra cost from a chat the person already pays for (Grok, ChatGPT, Gemini), in their own
browser, with no API key. Its limits are real: it sees only what is public or uploaded, it cannot press a
button and see what happens, and uploading screenshots of a private product to a third party is the
person's decision. So it is opt in, labelled in the report, used as a tie breaker and a check on
same-maker taste, and never counted toward "ready for people".

## Why fresh context, blind first, compare second

A reviewer who has seen the plan, the last scores, last round's screenshots, the design direction or the
other reviewer's verdict anchors on them: model judges pull toward prior scores and reference answers.
So the scoring brief gives only what a first-time user would know, and this round's screens. Constraints
a fix must respect (the config's `rules`) are listed apart and marked "not scored". The comparison with
last round, which is useful for catching regressions, is a separate labelled pass given to the reviewer
after its verdict is saved, and it never changes a score. The blind pass is the score of record.

## The noise check

A model judge does not give the same score twice: on an unchanged product a score moves a point or two
between runs. So every round each reviewer also scores a frozen control, the round 1 screens that never
change, as journey "control". How far that score moves is that reviewer's noise. The report shows the
band, and a journey change no bigger than it is marked "within noise" and does not drive the next round's
work. A real improvement is one that clears the band.

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
- **Stage 4, real people (optional)**: a few first-time users complete the journeys unaided; their time,
  stumbles and words are recorded beside the AI scores and shape the next round.

## When to stop: the stopping rule

"Ready for people" means all of this at once, and for two rounds in a row:

- every journey scores 9 or better from every counting reviewer (a web chat reviewer that only saw
  screenshots does not count);
- no high-severity fix is open;
- the reviewers are within 1 point of each other on every journey;
- it held last round too, so one lucky round does not end the loop.

If you can, a few real first-time people then try the journeys, and what they find shapes the next round.

Why not "every reviewer gives every journey 10"? In practice no journey reaches a unanimous 10: model
judges have a ceiling around 9, one run of a judge moves a point or two on an unchanged product (see the
noise check), and a perfect score from a proxy is more often a sign that the bar moved than that nothing
is left. So a unanimous 10 is shown as a flag to double check the brief and the journeys, not as the
finish. The tool also refuses a 10 that still proposes fixes, and an "if fixed" below the score, so both
numbers keep their meaning.

If the loop reaches `max_rounds` (default 6) without being ready, stop and talk to the person: the
journeys or criteria may ask for something the product should not do. Late rounds tend to drift into
generic advice; a round cap keeps the loop honest.
