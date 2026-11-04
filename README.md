# mStack

Skills for people and their AI agents, by Mark Hallam. Free and open source under the MIT licence.

A skill is a written method plus the small tools that carry it out. Every mStack skill is built for
humans and agents alike, and is **agent agnostic**: it works from whichever AI agent you already use
(Claude, Codex, Cursor, ChatGPT and others), not just one. The agent does the heavy lifting with your
permission; you make the calls.

## The skills

| Skill | What it does |
|---|---|
| [multi-evaluator](skills/multi-evaluator/SKILL.md) | Improves a product's design in rounds until every user journey scores 10 out of 10 from independent AI reviewers made by different companies, with before and after screenshots and a report every round. |

More skills will follow.

## multi-evaluator: keep improving until it is 10 out of 10

You describe what a real person must be able to do with your app, site or document (the **journeys**) and
what good looks like (the **criteria**: clear, quick, trust, familiar, calm, works everywhere, and more as
it matures). Then each round:

1. The same screens are captured the same way (desktop, phone, dark theme; light theme first), so before
   and after compare like for like.
2. At least two reviewers from different AI makers (by default Claude and Codex) each open the real
   product in a real browser, in fresh context, never told the expected answer. Each scores every journey
   0 to 10, says what the score would be if its fixes were made, and lists specific fixes by severity.
3. You get one HTML page: the score trend toward 10, each journey against last round, what changed, what
   the reviewers propose, before and after screenshots of every screen, and a filmstrip of every round.
4. The fixes are made, and the next round starts. When every reviewer gives every journey 10, real people
   try it. Where they disagree with the AI reviewers, the people win.

![An example report: the score trend, each journey against last round, and before and after screens](docs/sample-report.png)

The example above is [examples/sample-report.html](examples/sample-report.html)
([view it in your browser](https://htmlpreview.github.io/?https://github.com/mark-hallam/mstack/blob/main/examples/sample-report.html)),
made by the self-test from a tiny sample page. Its scores come from stand-in reviewers, so they are
illustrative only.

## Use it from your agent

**Claude Code** (as a plugin):

```
/plugin marketplace add mark-hallam/mstack
/plugin install mstack@mstack
```

Then ask: "Use the multi-evaluator skill to review my app until every journey is 10 out of 10."
Or, without the plugin, copy `skills/multi-evaluator` into `~/.claude/skills/`.

**Codex, Cursor, or any agent that reads AGENTS.md**: clone this repository next to your project, or open
it in your agent, and ask the same thing. [AGENTS.md](AGENTS.md) tells the agent where everything is.

**Any other agent** (ChatGPT, Gemini, and others that can run commands): give it this link and say what you
want: https://github.com/mark-hallam/mstack/blob/main/docs/agents.md

**By hand**: everything is one command line tool. Run
`python3 skills/multi-evaluator/scripts/eval_loop.py --help` to see the commands.

## What you need

- Python 3.9 or later and Node.js 18 or later. Standard library only: nothing to install.
- Google Chrome or Chromium, for the real browser the reviewers drive.
- For the default reviewers: an agent that can start a fresh-context reviewer (Claude Code does), and the
  [Codex command line tool](https://github.com/openai/codex) signed in. Any other reviewer with a
  non-interactive mode can be added in the config.

## Check it works

```
python3 tests/leak_scan.py
python3 tests/selftest.py
```

The self-test runs three review rounds on a tiny local page with stand-in reviewers (no AI and no network
beyond your own computer) and checks the report, before and after images, the filmstrip, the growing
criteria, and that bad replies are refused.

## Licence

MIT. Copyright (c) 2026 Mark Hallam. See [LICENSE](LICENSE).
