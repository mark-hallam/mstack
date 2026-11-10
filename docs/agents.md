# mStack: instructions for any AI agent

You have been pointed at this page by a person who wants to use mStack
(https://github.com/mark-hallam/mstack). Follow these steps. They work from any agent that can read web
pages and run commands on the person's computer: Claude, Codex, Cursor, ChatGPT with a terminal, Gemini
and others.

## 1. Get the skills

```
git clone https://github.com/mark-hallam/mstack.git ~/mstack
```

(If you cannot run commands, read the files on GitHub and tell the person which commands to run.)

Needs Python 3.9 or later. Node.js 18 or later and Google Chrome or Chromium are needed by multi-evaluator (the review
loop drives a real browser) and by design-direction's `shots` command (it captures each direction). away-mode uses
Chrome or Chromium for its pictures and PDFs when one is installed and otherwise falls back to the system's own
tools; it never needs Node.js. The other skills need only Python.

## 2. Make them switch on by themselves

The person should never have to name a skill. Run `python3 ~/mstack/skills/mstack/scripts/mstack.py session-start` once (it puts a launcher in
`~/.mstack/bin` that survives updates), then `python3 ~/mstack/skills/mstack/scripts/mstack.py routing`,
and follow the block it prints for the rest of this session. To keep it for every session, add that block
to your agent's global instructions (for Codex and Cursor, `mstack.py setup codex` or
`setup cursor --project <folder>` shows the change; write it with `--write` only after the person says yes).

## 3. The skills

<!-- mstack:catalog:start -->
| Skill | Switches on when |
|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. On by default: notify them without being asked. |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch with defaults, then run to a verified outcome without further input. |
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). |
| design-direction | Someone wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from: up to four whole working directions from one brief, a comparison page with a recommendation, the person's pick, structure-only variants with numbered questions, then a locked brand file. |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back. Notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for: a queue across every project on the cheapest fitting model, 15% of every usage window kept for them, drafts and side branches only, one morning digest. Also "what did the crew finish" and "what is my usage". |
| mstack | The person asks what is happening across their projects, wants a brief for another agent or a rules file for a project, switches a skill off or on, asks to "review my skills", or an mStack skill has just finished. |

What mstack offers (`mstack.py <command>`):

- `mstack.py status`: The person asks what is happening across all their projects or what is waiting on them.
- `mstack.py brief`: The person asks for a brief for a tester, reviewer, worker, researcher or security check they are about to start.
- `mstack.py rules`: The person wants a rules file for a project, or the same rules carried into every brief.
- `mstack.py disable <skill>`: The person says to switch a skill off for good (`enable <skill>` switches it back on). For one task, just do not use it.
- `mstack.py review`: The person asks to "review my skills", what their skills have learned, or to improve a skill.
- `mstack.py log <skill>`: After any mStack skill finishes: record privately how it went.
- `mstack.py setup codex`: The person wants mStack set up in Codex, Cursor (`setup cursor`) or Claude Code hooks (`setup claude-hooks`).
<!-- mstack:catalog:end -->

When one applies, read `~/mstack/skills/<skill>/SKILL.md` in full and follow it.

## Ground rules

- If `~/.mstack/config.json` lists a skill under `"disabled"`, or the person says not to use it, do not.
- Act only with the person's permission. Never change their settings files without showing the change
  and getting a yes. Never submit real payments, messages or personal data while reviewing.
- Everything mStack records stays on the person's computer in `~/.mstack`.
- Tell the person plainly what you did, what passed, and what you could not check.
