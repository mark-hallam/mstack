---
name: mstack
description: mStack's always-on index. Lists every mStack skill and when each switches on by itself, so the person never has to name one. Use at the start of any substantial task to see which mStack skills apply; when the person says to switch an mStack skill off or on, or "don't use <skill>" for a task; when they ask to "review my skills", "what have my skills learned", "improve a skill", "which skills do I have", or to see what an mStack skill has learned (not for creating a new skill from scratch); when they ask what is happening across all their projects or what is waiting on them (`mstack status`); when they ask for a brief for a tester, reviewer, worker, researcher or security check they are about to start (`mstack brief`); when they want a rules file for a project (`mstack rules`); after any mStack skill finishes, to record privately how it went; and to set mStack up in Codex, Cursor or Claude Code hooks.
---

# mStack

mStack is a set of skills for people and their AI agents. Installing mStack (or any one of its skills)
makes all of them available, and each switches on by itself when its moment comes. The person never has
to call one by name.

The shared tool is `scripts/mstack.py` (next to this file). Below, `MSTACK` means
`python3 <this skill's folder>/scripts/mstack.py`.

## The skills, and when each switches on

<!-- mstack:catalog:start -->
| Skill | Switches on when | Default |
|---|---|---|
| ping-me | You need the person's decision or input, or a task they asked for is complete or blocked. On by default: notify them without being asked. | On |
| outcome-first | Any task bigger than a few steps: pin the outcome, ask every question in one batch with defaults, then run to a verified outcome without further input. | On |
| multi-evaluator | Someone wants a product's design reviewed and improved in rounds by independent AI reviewers from different makers until it is ready for real people (every journey 9 or better, reviewers agreeing, no high fix open, two rounds running). | On |
| design-direction | Someone wants to find the look of a new product, choose between design directions, or make on-brand variants to pick from: up to four whole working directions from one brief, a comparison page with a recommendation, the person's pick, structure-only variants with numbered questions, then a locked brand file. | On |
| away-mode | You are about to present a file, report, mockup, screenshot or link, or the person says they are on their phone, away, out or back. Notice when they are away and deliver phone-readable copies (PNG, PDF, files in the chat, key points in the reply). | On |
| crew | The person wants work to carry on in the background while they are away or asleep, within the usage they already pay for: a queue across every project on the cheapest fitting model, 15% of every usage window kept for them, drafts and side branches only, one morning digest. Also "what did the crew finish" and "what is my usage". | On |
| mstack | The person asks what is happening across their projects, wants a brief for another agent or a rules file for a project, switches a skill off or on, asks to "review my skills", or an mStack skill has just finished. | On |

What mstack offers (`MSTACK <command>`):

- `MSTACK status`: The person asks what is happening across all their projects or what is waiting on them.
- `MSTACK brief`: The person asks for a brief for a tester, reviewer, worker, researcher or security check they are about to start.
- `MSTACK rules`: The person wants a rules file for a project, or the same rules carried into every brief.
- `MSTACK disable <skill>`: The person says to switch a skill off for good (`enable <skill>` switches it back on). For one task, just do not use it.
- `MSTACK review`: The person asks to "review my skills", what their skills have learned, or to improve a skill.
- `MSTACK log <skill>`: After any mStack skill finishes: record privately how it went.
- `MSTACK setup codex`: The person wants mStack set up in Codex, Cursor (`setup cursor`) or Claude Code hooks (`setup claude-hooks`).
<!-- mstack:catalog:end -->

`MSTACK skills` prints the same list with each skill's state. The table above and the ones in AGENTS.md and
`docs/agents.md` are generated from `catalog.json` (next to this file): change a line there, then run
`MSTACK catalog --write`; `MSTACK catalog --check` exits 1 and names any file that has drifted. Read a skill's `SKILL.md` when it switches on.

## Switching skills off

- For good: `MSTACK disable <skill>` (and `enable <skill>`). This writes `~/.mstack/config.json`:
  `{"disabled": ["ping-me"]}`. The person can also edit that file by hand. It also holds `max_questions`
  (how many questions outcome-first asks in one batch, default 6).
- For one task: if the person says "don't use <skill>" (or "no pings", "just do it", and so on), do not use
  it for that task. No file changes.
- Every mStack skill checks the config before it starts. `MSTACK enabled <skill>` exits 0 when it is on.
- Skill names are checked: `log`, `learn`, `learned`, `unlearn`, `enabled`, `disable` and `enable` accept only the
  names `MSTACK skills` lists. Any other name exits 2 with the valid names and writes nothing.
- Every `MSTACK` command takes `--json` and then prints one JSON object; an error is `{"ok": false, "error": "..."}`
  with a non-zero exit.

**The off switch is that one file and nothing else.** Switching a skill off, for good or for a task, never
edits CLAUDE.md, AGENTS.md, `.cursor/rules`, `settings.json`, `config.toml` or any other instructions or
settings file, and never works around `MSTACK_HOME` (if it is set, that is the home to use; never unset it
to reach the person's real `~/.mstack`). If the person wants a rule written into their own instructions
file, they write it, or they ask for exactly that and see the change first.

## Getting better, privately

Each skill learns from how it is used, on this computer only. Nothing leaves the machine unless the person
chooses to share an improvement.

1. **After every use** of an mStack skill, record how it went in one line:
   `MSTACK log <skill> --outcome reached|partial|not-reached --needed-user "<where it needed the person>" --stalled "<where it stalled>" --correction "<what the person corrected>"`
   (each flag can repeat; leave out what did not happen). It goes to `~/.mstack/journal/<skill>.jsonl`.
2. **"Review my skills"** (when the person asks, or once when the session start note says a review is due):
   - `MSTACK review --json` gathers the journal since the last review into evidence per skill. It only reads:
     run it as often as you like, it changes nothing and gives the same answer.
   - For each skill with new uses, read its `SKILL.md` and the evidence, and propose concrete edits: a rule
     to add ("Ask about the deploy target in the first batch of questions") or a change to the skill's
     wording. One line each, with the evidence behind it.
   - Show them to the person in one batch. Record each accepted one: `MSTACK learn <skill> "<rule>"`.
     Accepted rules live in `~/.mstack/learned/<skill>.md`, survive mStack updates, and win over the
     skill's own file.
   - Then `MSTACK review --done` marks the journal reviewed and writes the day's evidence file
     (`~/.mstack/reviews/<day>.md`). Until it has run, the session start note keeps saying a review is due.
3. **Seeing and removing what was learned**: `MSTACK learned` lists every skill that has learned rules, numbered;
   `MSTACK learned <skill>` lists one skill's rules. `MSTACK unlearn <skill> <n>` removes rule number n (as
   numbered by `learned`) and prints what it removed.
4. **Sharing an improvement** is the person's choice: `MSTACK learned <skill>` prints what was learned, and
   they can open an issue or pull request on github.com/mark-hallam/mstack with it if they want to.

## A rules file per project

The person should not have to retype the same rules into every brief. One rules file per project lives in the
mStack home (`~/.mstack`, or `$MSTACK_HOME`), **never in the repository**, because never-touch paths, ports and
test families are private. A global file (`~/.mstack/rules.md`) holds what applies everywhere. The project's
file (`~/.mstack/projects/<slug>/rules.md`) is found from the project folder or any folder inside it, so a
worktree finds it too. Both have the same six headings, one rule per line starting with `- `:
`## Never touch`, `## Never print`, `## Test targets`, `## Voice`, `## Working rules`, `## Done rules`.
The project's rules come first, then the global ones it did not already say. A project heading whose only rule
is `- none` drops the global rules under that heading.

- `MSTACK rules init [--global] [--project <folder>]` writes the template (it never overwrites without `--force`).
- `MSTACK rules show [--project <folder>] [--brief]` prints the merged rules; `--brief` is the block to paste
  into a brief you write for another agent. The crew, multi-evaluator and design-direction briefs add it themselves.
- `MSTACK rules import` reads the person's feedback memories and only **proposes** rules, numbered. Nothing is
  written until `MSTACK rules accept <n> ...` (only `accept` writes rules from memories). From any other agent,
  point it at the notes you have instead: `MSTACK rules import --from <file or folder>` (repeatable; any
  Markdown or text files, bullet lines become proposals under the matching heading).
- `MSTACK rules list` shows every known project.

Keep real secrets out of the file: a rule may name a kind of secret ("the family name"), never the secret.

## Status across everything

`MSTACK status [--project <folder>] [--json] [--render] [--days N]` (run `python3 <mstack skill folder>/scripts/status.py status`
directly if you prefer) shows every project mStack knows in one view. Projects are found from the rules files, the
outcomes, the crew config and queue, and the review folders under the mStack home, and merged by folder. **"Waits for
you" is always first**: open outcome questions (with their defaults), crew questions, reviews waiting for the person's
fixes and blocked outcomes, each with the command that answers it. Then one block per project (where it is, the State
lines of its HANDOFF.md, what is running, the latest review, what shipped last, whether it has a rules file), folders
that are gone, and the crew's usage against the cap. Use it when the person asks what is happening across their
projects. It only reads. `--render` writes `status.md` in today's outbox and makes a PDF and a phone-width picture of
it; send those when the person is away. `--days N` (default 7) limits the running work and reviews shown; what waits
for the person is never limited.

## Briefs in one line

The person should not have to type a brief. `MSTACK brief <kind> "<one line goal>" [--project <folder>]
[--read <file> ...]` writes a complete brief to `~/.mstack/briefs/` and prints it: what to read first, the
project's rules file (read on every brief, so a gap is shown when there is none), the job, the output format
and the same finishing block crew uses. The five kinds:

- `tester`: plays a persona from the rules file against `--target`, quotes the screen, ends with `RELEASE` or `HOLD`.
- `reviewer`: scores blind in the multi-evaluator reply format (`--persona` optional).
- `worker`: a coding job; `--worktree` makes a git worktree and a `work/<slug>` branch for it.
- `research`: reads only, every claim tagged VERIFIED or UNCONFIRMED.
- `security`: checks a repository for committed secrets and unchecked input, and changes nothing.

Other options: `--previous <report>` (tester re-grades the earlier findings first), `--unattended` (ask nothing,
take the defaults), `--json`. `--run claude|codex|cursor` (or a runner from the crew config) starts the brief
and saves the reply beside it as `<brief>.reply.md`; `--model <name>` passes the model. The tool never commits,
pushes or sends anything itself.

## Setting mStack up in each agent

- **Notification text**: a hook or Codex notification says only "Turn finished in <project folder>" (or "Waiting for
  you in <project folder>"). The agent's reply text is private by default and stays out, including from ntfy. The
  person can add the first 160 characters of the reply by setting `"notify_reply_text": true` in
  `~/.mstack/config.json`; every `setup` preview and `ping test` say what text a notification carries and where it goes.
- **Undoing a setup**: every `setup` form takes `--remove` (a preview first, then `--write`). It takes out only what
  mStack added, puts a chained `notify` line back exactly as it was, and deletes a file mStack created when nothing
  else is in it. If the file is a symbolic link, the preview names the real file that changes.
- **Claude Code**: install the plugin (`/plugin marketplace add mark-hallam/mstack`, then
  `/plugin install mstack@mstack`). Its session start hook adds the always-on rules to every session.
- **Codex**: `MSTACK setup codex` shows what it would add: mStack's routing block in `~/.codex/AGENTS.md`
  (Codex reads that file in every session; without the block the skills are visible but switch on less
  reliably) and ping-me's `notify` line in `~/.codex/config.toml`. If a `notify` program is already there,
  it is chained, not replaced: mStack pings first, then the person's own program runs with the same event;
  the original line is kept in a comment and a `.mstack-backup` copy. Ask the person, then run it again
  with `--write`. Run it again after an mStack update to refresh the block. `MSTACK setup codex --remove` takes
  both back out.
- **Cursor**: `MSTACK setup cursor --project <folder>` shows an always-applied rule for that project. Ask,
  then `--write`. `--remove` deletes the rule file it wrote.
- **The launcher**: `session-start` and every `setup ... --write` keep `~/.mstack/bin/mstack.py` and
  `~/.mstack/install.json` current. Hooks, the Codex notify line and the routing block for other agents call the
  launcher (`mstack.py <command>`, `mstack.py tool <skill> <script> ...`, `mstack.py where [<skill>]`), so they keep
  working when a plugin update moves the skills folder.
- **Any other agent**: `MSTACK routing` prints the block to paste into its instructions, or point it at
  https://github.com/mark-hallam/mstack/blob/main/docs/agents.md.

Never change the person's settings files without showing them the change and getting a yes.
