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

Needs Python 3.9 or later. multi-evaluator also needs Node.js 18 or later and Google Chrome or Chromium.

## 2. Make them switch on by themselves

The person should never have to name a skill. Run `python3 ~/mstack/skills/mstack/scripts/mstack.py routing`
and follow the block it prints for the rest of this session. To keep it for every session, add that block
to your agent's global instructions (for Codex and Cursor, `mstack.py setup codex` or
`setup cursor --project <folder>` shows the change; write it with `--write` only after the person says yes).

## 3. The skills

| Skill | Switches on when |
|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. On by default: notify them without being asked. |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch with defaults, then run to a verified outcome. |
| multi-evaluator | The person wants their site, app or document reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). |
| design-direction | The person wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from (up to four whole directions from one brief, a comparison page with a recommendation, structure-only variants, a locked brand file). |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back. Notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). On by default. |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for: a queue across projects on the cheapest fitting model, their 15% of every usage window kept, drafts and side branches only, a morning digest. Also "what did the crew finish" and "what is my usage". |
| mstack | The person switches a skill off or on, asks to "review my skills", or an mStack skill finishes (record privately how it went). |

When one applies, read `~/mstack/skills/<skill>/SKILL.md` in full and follow it.

## Ground rules

- If `~/.mstack/config.json` lists a skill under `"disabled"`, or the person says not to use it, do not.
- Act only with the person's permission. Never change their settings files without showing the change
  and getting a yes. Never submit real payments, messages or personal data while reviewing.
- Everything mStack records stays on the person's computer in `~/.mstack`.
- Tell the person plainly what you did, what passed, and what you could not check.
