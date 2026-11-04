# mStack

Skills for people and their AI agents, by Mark Hallam. Free and open source under the MIT licence.

A skill is a written method plus the small tools that carry it out. Every mStack skill is built for
humans and agents alike, and is **agent agnostic**: it works from whichever AI agent you already use
(Claude, Codex, Cursor, ChatGPT and others), not just one. The agent does the heavy lifting with your
permission; you make the calls.

**You never have to call a skill by name.** Install mStack (or any one of its skills) and every skill is
there, switching on by itself when it is relevant. Switch any of them off whenever you like.

## The skills

| Skill | What it does | Default |
|---|---|---|
| [ping-me](skills/ping-me/SKILL.md) | Tells you on your phone and watch, without being asked, whenever your agent needs your decision or input, or a task you asked for is done or blocked. So you can walk away. | On |
| [outcome-first](skills/outcome-first/SKILL.md) | The path of least resistance: your agent pins down the outcome you want, asks every question once (with sensible defaults), then works to a verified result on its own, in parallel, surviving restarts and usage limits, and reports once. | On |
| [multi-evaluator](skills/multi-evaluator/SKILL.md) | Improves a product's design in rounds until every user journey scores 10 out of 10 from independent AI reviewers made by different companies, with before and after screenshots and a report every round. | On |
| [away-mode](skills/away-mode/SKILL.md) | Notices by itself when you are away from your computer and following from your phone, and presents every output in a form the phone can show: screenshots, PDFs, files sent to the chat, and the key points in the message. No more asking for a screenshot. | On |
| [mstack](skills/mstack/SKILL.md) | The index: which skills switch on when, the on and off switches, and private self-improvement ("review my skills"). | Always |

### ping-me: walk away, get pinged

Whenever your agent needs you (a decision, an approval, something only you can do) or finishes or gets
stuck on something you asked for, it notifies you straight away, in one short line that leads with what
you need to do. What honestly reaches your phone: in Claude Code, with Remote Control connected, the
Claude app delivers it to your phone and watch; in Codex, Cursor and headless runs the ping is a desktop
alert on the computer, which does not reach a phone, unless you opt in to ntfy, a free phone push app
(`mstack.py setup ntfy` walks you through it and writes nothing until you say yes; it is off by default
because it sends the text to a third party). For extra reliability it can add platform hooks (Claude
Code's `Notification` and `Stop` events, Codex's `notify` setting), always showing you the change and
asking first. "No pings" for one task is forgotten next session by design; the off switch in
`~/.mstack/config.json` is remembered.

### outcome-first: ask once, then done

For any real piece of work, your agent first works out everything it will need and asks it all in one go,
with defaults so you can just say "go". Then it plans the work so independent parts run in parallel, keeps
a progress file that survives restarts, schedules its own resume if a usage limit stops it, and only stops
when the outcome is proven with evidence (tests passing, a page loading, a file you can open), not on its
own say-so. You hear from it again when it is done, or when a decision is genuinely yours.

### multi-evaluator: keep improving until it is 10 out of 10

You describe what a real person must be able to do with your app, site or document (the **journeys**) and
what good looks like (the **criteria**: clear, quick, trust, familiar, calm, works everywhere, and more as
it matures). Each round, the same screens are captured the same way; at least two reviewers from different
AI makers (by default Claude and Codex) each drive the real product in a real browser, in fresh context,
and score every journey 0 to 10 with an "if fixed" score and specific fixes. You get one HTML page with
the score trend, each journey against last round, the proposals, and before and after screenshots with a
filmstrip of every round. When every reviewer gives every journey 10, real people try it, and where they
disagree with the AI reviewers, the people win.

![An example report: the score trend, each journey against last round, and before and after screens](docs/sample-report.png)

The example above is [examples/sample-report.html](examples/sample-report.html)
([view it in your browser](https://htmlpreview.github.io/?https://github.com/mark-hallam/mstack/blob/main/examples/sample-report.html)),
made by the self-test from a tiny sample page. Its scores come from stand-in reviewers, so they are
illustrative only.

### away-mode: following from your phone, without asking for screenshots

You start a job at your desk and follow it from your phone. From there you cannot click a local path, run
an `open` command or look at a file on the computer. Before presenting anything, your agent checks whether
you are away: your own words win ("I'm on my phone", "I'm back"), then what the harness tells it (you are
following from another device, a push was not sent because you are at the terminal), then the machine
itself (keyboard and mouse idle for 10 minutes, a locked screen, a sleeping display). When you are away, or
it cannot tell, it makes phone-readable copies (an HTML report becomes a PDF and a phone-width light-theme
screenshot; Markdown becomes HTML then PDF; a local web app becomes desktop and phone screenshots), sends
them into the chat, and puts the 3 to 5 key points in the message itself. Never just a path. When you are
back at the computer, local links and `open` commands return.

## Install

**Claude Code** (as a plugin):

```
/plugin marketplace add mark-hallam/mstack
/plugin install mstack@mstack
```

That is all. A session start hook tells Claude which skills exist and when each applies, so they switch
on by themselves. (Without the plugin, copy the folders in `skills/` into `~/.claude/skills/`.)

**Codex**: clone this repository, then ask Codex to run
`python3 skills/mstack/scripts/mstack.py setup codex`. It shows what it would add to `~/.codex/AGENTS.md`
(so the skills switch on by themselves) and `~/.codex/config.toml` (ping-me; a `notify` program you already
have is chained, not replaced), and writes it only after you say yes. Both steps matter: without the
AGENTS.md block Codex can see the skills but picks them less reliably.

**Cursor**: `python3 skills/mstack/scripts/mstack.py setup cursor --project <your project>` adds an
always-applied rule, after showing it to you.

**Any other agent** (ChatGPT, Gemini, and others that can run commands): give it this link and say what you
want: https://github.com/mark-hallam/mstack/blob/main/docs/agents.md

## Switching skills off

- Everywhere: `python3 skills/mstack/scripts/mstack.py disable ping-me` (or `enable`), or edit
  `~/.mstack/config.json` yourself: `{"disabled": ["ping-me"]}`.
- For one task: just tell your agent, for example "don't use outcome-first for this" or "no pings".

## Skills that get better, privately

After each use, your agent records one line about how it went (the outcome, where it needed you, where it
stalled, what you corrected) in `~/.mstack/journal/` on your own computer. Every so often, or when you say
"review my skills", it gathers that into evidence and proposes specific improvements. You accept the ones
you want, and they are kept in `~/.mstack/learned/`, surviving updates. Nothing leaves your computer unless
you choose to share an improvement (for example as an issue or pull request here).

## What you need

- Python 3.9 or later and Node.js 18 or later. Standard library only: nothing to install.
- For multi-evaluator: Google Chrome or Chromium, and for the default reviewers an agent that can start a
  fresh-context reviewer (Claude Code does) plus the [Codex command line tool](https://github.com/openai/codex).
- For away-mode's PDFs and screenshots: Google Chrome or Chromium (it falls back to the system's own tools
  on macOS, and says plainly when nothing can render).

## Check it works

```
python3 tests/run_all.py
```

This runs the leak and style scan, the packaging checks, and each skill's self-test: switches, pings (to a
stand-in, never your real desktop), the private journal and reviews, the setup for each agent (on temporary
copies of the settings files), the outcome plan with a stand-in crontab, away detection with stand-in
machine signals plus a real render when Chrome is present, and three review rounds on a tiny local page
with stand-in reviewers (no AI and no network beyond your own computer).

## Licence

MIT. Copyright (c) 2026 Mark Hallam. See [LICENSE](LICENSE).
