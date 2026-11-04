# mstack-eval.json, field by field

The review folder holds one `mstack-eval.json`. `eval_loop.py init` writes a starter copy from
`templates/mstack-eval.json`. Placeholders in braces are filled in when a command runs.

## About the product

| Field | What it is |
|---|---|
| `name` | The product's name, shown in briefs and the report. |
| `about` | One short paragraph for reviewers who have never seen it: what it is, who it is for, what it promises. Not the design direction: that goes in `rules`, so the scoring pass stays blind. |
| `rules` | Optional list of constraints a fix must respect (the design direction, a locked brand, "no new pages"). Shown to reviewers as "not scored". |
| `persona` | Who the reviewers judge as, finishing the sentence "Judge it as this person: ...". |
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
- `kind: "command"`: `review` runs the command with the brief on standard input. Placeholders: `{work}`
  (the reviewer's own work folder), `{reply}` (a file the reviewer may write its final reply to; otherwise
  standard output is read), `{brief}`, `{round}`, `{dir}`.
- `shared_chrome: true`: for sandboxed reviewers that cannot start Chrome. `review` starts a headless
  Chrome on port 9555 (change with `--cdp-port`) and the brief tells the reviewer to use it.

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
