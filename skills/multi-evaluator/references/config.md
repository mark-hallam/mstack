# mstack-eval.json, field by field

The review folder holds one `mstack-eval.json`. `eval_loop.py init` writes a starter copy from
`templates/mstack-eval.json`. Placeholders in braces are filled in when a command runs.

## About the product

| Field | What it is |
|---|---|
| `name` | The product's name, shown in briefs and the report. |
| `about` | One short paragraph for reviewers who have never seen it: what it is, who it is for, what it promises. Not the design direction: that goes in `rules`, so the scoring pass stays blind. |
| `rules` | Optional list of constraints a fix must respect (the design direction, a locked brand, "no new pages"). Shown to reviewers as "not scored". |
| `brand` | Optional path (relative to the review folder, or absolute) to a `brand.json` made by the design-direction skill's `lock`. Its `rules` are listed under "Rules your fixes must respect (not scored)" in every scoring brief, after `rules`. |
| `persona` | Who the reviewers judge as, finishing the sentence "Judge it as this person: ...". |
| `personas` | Optional list of named people, each `{"id": "child", "who": "a seven year old who reads short words"}`. A journey may name one with `"persona": "child"`; the scoring brief then says "Play this person: ..." on that journey's line. `brief` refuses a journey that names an id not listed here. |
| `note` | Optional line under the report's title (for example "Fictional demo data."). |

## `target`: how to reach the product

| Field | What it is |
|---|---|
| `url` | Its address. `{port}` is a free port chosen for each run. For a site already running, a fixed address and no `start`. |
| `start` | Optional command that starts it, as a string (run by the shell) or a list. Use `{port}`, and `{tmp}` for a fresh temporary folder made for this run. |
| `cwd` | The folder `start` and `setup` run in, relative to the review folder. |
| `setup` | Optional commands run before `start`, for example copying demo data into `{tmp}`: `"cp -R ../examples/demo {tmp}/data"`. |
| `env` | Extra environment variables for `setup` and `start` (placeholders work here too). |
| `ready_timeout` | Seconds to wait for the address to answer (default 30). |

Every capture and every `serve` gets its own port and its own `{tmp}`, so runs never share state and the
product's own files are never changed.

## `viewports` and `views`: the fixed screens

`viewports` names screen sizes. The defaults are `desktop` (1440 by 1000) and `phone` (390 by 844, mobile,
touch, double density).

Each view in `views` is captured every round, the same way:

```json
{"id": "detail-phone", "name": "An item opened", "group": "Phone", "viewport": "phone", "scheme": "light",
 "steps": [{"do": "goto", "url": "{url}"}, {"do": "click", "text": "Follow-up"}]}
```

- `id`: a short, stable name. Keep it the same across rounds so before and after line up.
- `group`: the heading the view sits under in the report (Desktop, Phone, Dark theme, First run).
- `scheme`: `light` (the default) or `dark`.
- `steps`: journey driver steps (see the top of `scripts/drive.mjs`). The screenshot after the last step is kept.
- `target`: optional overrides of the target for this view only (for example a different `setup` that
  starts the product with no data, for a first run screen).

## `journeys`

```json
{"id": 1, "name": "Clear the day", "viewport": "desktop 1440x1000", "task": "Open the app. Understand what needs you today and why, ..."}
```

Write each as a real person's task, end to end, with what done looks like. Never write the expected answer.

A journey may add `"persona": "child"` (an id from `personas`) to be played by that person instead of the
default `persona`. For example, with `"personas": [{"id": "child", "who": "a seven year old who reads short words"}]`
in the config, `{"id": 2, "name": "Join a game", "persona": "child", "task": "..."}` is scored as that child.

## `criteria` and `stages`

`criteria` is the floor every round uses: `{"name": "Clear", "means": "obvious what to do next and why, no jargon."}`.

`stages` add criteria as the product matures. A stage applies when `"active": true`, or from round
`"from_round": <n>`. `start-round` saves the criteria in force to `rounds/r<N>/criteria.json`, so the
report shows which criteria each round used and older rounds stay comparable.

## `control`: the noise check

```json
"control": {"task": "Judge these screens as a first-time visitor: is it clear what this is and what to do first?"}
```

Optional. When set, the first `capture` copies that round's fixed screens (PNG, visible text) to
`<review folder>/control/` and they never change. Every round, each reviewer also scores them as journey
`control` (the brief says so, and `verdict` refuses a reply without it). How far a reviewer's control score
moves between rounds is that reviewer's noise; the report shows it and marks any journey change no bigger
than it as "within noise". Switch it on: one extra journey per reviewer per round is cheap, and without it
a one point move looks like progress.

## `reviewers`

```json
{"id": "claude", "name": "Claude", "maker": "Anthropic", "colour": "#C15F3C", "kind": "agent"}
{"id": "codex", "name": "Codex", "maker": "OpenAI", "colour": "#1f6feb", "kind": "command", "shared_chrome": true,
 "timeout_minutes": 60,
 "command": ["codex", "exec", "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
             "--skip-git-repo-check", "-C", "{work}", "-o", "{reply}", "-"]}
```

- `kind: "agent"`: the agent running the loop starts this reviewer itself, in fresh context, with the brief,
  and saves the reply with `verdict`.
- `enabled`: optional. When `false`, `brief` and `review` skip this reviewer and readiness does not count it.
- `maker` and `model`: optional. Recorded on every saved verdict and shown in the report header as
  `Name (maker, model)`, so a reader can tell which company's model actually ran.
- `kind: "command"`: `review` runs the command with the brief on standard input. Placeholders: `{work}`
  (the reviewer's own work folder), `{reply}` (a file the reviewer may write its final reply to; otherwise
  standard output is read), `{brief}`, `{round}`, `{dir}`, `{home}` (the person's home folder).
- `shared_chrome: true`: for sandboxed reviewers that cannot start Chrome. `review` starts a headless
  Chrome on port 9555 (change with `--cdp-port`) and the brief tells the reviewer to use it.
- `usage`: optional, `"claude"`, `"codex"` or `"none"`: whose plan this reviewer spends, so `preflight` can
  read how much is left and when it resets. A command starting with `claude` or `codex` is recognised by
  itself; set it for an agent reviewer (the starter's Claude reviewer has `"usage": "claude"`) or a
  command that runs one of those plans through another program. Anything else shows usage "unknown".
- `signin_check`: optional command whose exit code 0 means signed in (as a list, or a string run by the
  shell). Without it, `preflight` uses `claude auth status`, `codex login status` or `cursor-agent status`
  when the command starts with one of those, and says "unknown" otherwise. Only yes or no is kept, never
  the check's output (it may name the account).
- `backup`: optional, the id of another reviewer in this file (often one with `"enabled": false`) that may
  stand in when this one hits its usage limit and too few reviewers are left. It is used only when the
  person chooses it (`choose --choice backup`); it then counts as itself, under its own maker, so a
  backup from the same maker keeps the different-makers rule honest.

### Usage limits during a round

`preflight` (run by `brief` and `review` too, or on its own; `--json` for agents) lists each enabled
reviewer's state: `ready`, `by-agent` (your own agent runs it), `paused` (a usage window at 99% or more
that resets later), `missing` (program not found) or `signed out`. A reviewer at 90% or more runs, with a
warning that it may stop partway.

A reviewer that hits its limit during `review` is recorded in `rounds/r<N>/availability/<id>.paused.json`
with the reset time when it can be read. If at least two counting reviewers from different makers remain
(a reviewer without `maker` counts as its own maker), the round continues short one reviewer. Otherwise
`review` exits with code 3, runs `notify`, and `status --json` carries `availability` with
`choice_needed`, `question`, `choices` (`wait`, `backup`, `fewer`) and `how_to_answer`. The person's answer
is saved by `choose --choice <wait|backup|fewer>` in `rounds/r<N>/availability/choice.json`. A round run
with `fewer` never counts toward ready for people. A later verdict from the paused reviewer clears its pause.

### Cursor's command line agent (`kind: "command"`)

The starter file has this entry, switched off. Set `"enabled": true` to use it.

```json
{"id": "cursor", "name": "Cursor agent", "model": "", "colour": "#555",
 "kind": "command", "enabled": false, "shared_chrome": true, "timeout_minutes": 60,
 "command": ["cursor-agent", "-p", "--trust", "-f", "--output-format", "text", "--workspace", "{work}"]}
```

The brief arrives on standard input. What each part of the command does, so you know what you allow:

- `cursor-agent`: the program name, found on your `PATH`. If it is installed somewhere else, put its full path
  here. When it cannot be found, `review` says which program is missing and points back to this setting.
- `-p`: print mode. It runs once without a chat window, reads the brief, and prints its reply.
- `--trust`: trusts the working folder without asking, so it does not stop at a prompt nobody is there to answer.
- `-f`: lets it run shell commands without asking each time. The reviewer needs this to drive the product in a
  real browser. It means the agent can run any command in that session, so use it only with a folder and a
  product you are happy for it to work in. `--mode ask` refuses tools, so it cannot drive the product.
- `--output-format text`: prints the reply as plain text, which is what the loop reads.
- `--workspace {work}`: the reviewer's own folder for this round. Never point it at the product folder: the
  brief's rule "never change the product's own files" is the only guard.

The model: an empty `model` means the program uses its own default. To pick one, add `"--model", "<name>"` to
`command` (list the names with `cursor-agent --list-models`) and put the same name in `model` and its maker in
`maker`, so the report shows which model ran. `maker` is the model's maker, not the tool's. Only use models the
person's Cursor plan includes. Usage comes from that plan; no API key. An older config may
still call the entry `cursor-grok` with a fixed path and model: it keeps working as it is.

Other command reviewers work the same way, for example Claude Code without the agent:
`["claude", "-p", "--allowedTools", "Bash,Read,Write"]`, or any agent with a non-interactive mode.
Use at least two reviewers from different AI makers.

### An optional third reviewer through a web chat (`kind: "chat"`)

```json
{"id": "grok", "name": "Grok", "maker": "xAI", "kind": "chat", "url": "https://grok.com", "colour": "#555"}
```

A reviewer the person already pays for, used in their own signed-in browser (Grok, ChatGPT, Gemini), with
no API key. It is **opt in and never automatic**: the person names the chat and says what may be shared.
`brief` writes it a paste-ready brief; `review` and `status` tell the agent to open a new private chat in
the person's browser, paste the brief, upload this round's fixed screens if the product is not public,
save the reply and run `verdict`. What it saw is recorded (`"saw": "live"` only when the target address is
public; otherwise `"screenshots"`) and the report labels it. A chat reviewer cannot press a button and see
what happens, so it is a tie breaker and a check on same-maker taste: it never counts toward "ready for
people", and it can never be the only reviewer (`brief` refuses). Use the chat's private or temporary mode
and close the tab after.

## `notify`

Optional. A command run when a report is built, with `{message}` filled in, so a phone can buzz when a
round needs the person. For example, with the free ntfy app:

```json
"notify": {"command": ["curl", "-s", "-d", "{message}", "https://ntfy.sh/<a-private-topic-name>"]}
```

`eval_loop.py notify --dir <folder> "test"` sends a test message.

## Environment variables

| Variable | What it does |
|---|---|
| `MSTACK_CDP_PORT` | The driver uses an already running Chrome on this debugging port instead of starting its own. |
| `MSTACK_CHROME` | The Chrome or Chromium program, if it is not in a usual place. |
| `MSTACK_CHROME_ARGS` | Extra Chrome flags, for example `--no-sandbox` in some Linux containers. |
| `MSTACK_TMP` | Where temporary folders go (default `/tmp` on macOS, the system temporary folder elsewhere). |
