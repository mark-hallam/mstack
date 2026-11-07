# crew's config, field by field

`~/.mstack/crew/config.json` (or `$MSTACK_HOME/crew/config.json`). Private: it names the person's own
folders and is never inside a repository. `crew.py init` writes the starter in `templates/config.json`.

## Top level

| Field | Default | Meaning |
|---|---|---|
| `reserve_percent` | 15 | The person's share of every usage window. Crew uses a runner only while its fullest window is below `100 - reserve_percent`. At the reserve it stops and asks once per window. |
| `quiet_hours` | `{"start": "22:00", "end": "07:00"}` | When the person is not using their own sessions. Heavy jobs run only in quiet hours or when away-mode says the person is away. A runner whose usage cannot be read runs only in quiet hours. May span midnight. |
| `heavy_tokens` | 200000 | A job estimated above this (or on the `top` tier) is heavy. |
| `usage_max_age_minutes` | 90 | A reading older than this is stale; crew reads again (Codex: its session log; Claude: one word on the smallest model, if `probe` is true). |
| `probe` | true | Allow the one word read for Claude when no reading is fresh. It costs a little usage; set false to rely on readings from crew's own runs only. |
| `conservative.jobs_per_day` | 3 | The daily cap for a runner whose usage cannot be read. |
| `digest.at` | `"07:00"` | After this time, the first tick of the day writes and sends the digest. |
| `tick_minutes` | 15 | How often the background job wakes (what `install --every` writes). |
| `tests_every_minutes` | 120 | How often a `tests` source actually runs the test command. |
| `job_timeout_minutes` | 90 | A run longer than this is stopped and the job marked failed. |
| `max_attempts` | 3 | How many times crew tries a job automatically before parking it (never above 3). |
| `runners` | see below | How each runner is called. |
| `projects` | `[]` | The projects and their sources. |

## Runners

```json
"runners": {
  "claude": {"command": ["claude", "-p"], "models": {"small": "haiku", "fast": "sonnet", "top": "opus"},
             "probe_model": "haiku", "extra_args": []},
  "codex":  {"command": ["codex", "exec"], "models": {}, "extra_args": []}
}
```

- `command`: the program and its fixed arguments. Crew adds the brief, the output format, the model for the
  job's tier, and for Claude an allowed tools list built from the project (read, edit, search, `git add`,
  `git commit`, `git status`, `git diff`, `git log`, and the first word of the test command); for Codex the
  `workspace-write` sandbox and the worktree as `-C`.
- `models`: the model per tier. An empty map means the runner's own default for every tier (Codex on a
  ChatGPT plan may refuse smaller models; leave it empty unless the person has checked).
- `extra_args`: anything else the person wants (for example a permission flag they accept for unattended
  runs). Crew never adds a permission flag by itself.

## Projects

```json
{"id": "notes-app", "path": "~/code/notes-app", "branch": "main", "stream": "products", "mode": "branch",
 "github": true, "allow_push": false, "test": "python3 -m unittest discover -s tests",
 "notes": "Plain English in every file.", "allowed_tools": [], "sources": [ ... ]}
```

| Field | Meaning |
|---|---|
| `id` | Short name, used in job ids and the digest. Defaults to the folder name. |
| `path` | The project folder (`~` is expanded). |
| `branch` | The branch side branches are cut from. Defaults to the current branch. Must exist. |
| `stream` | A label for the digest: for example `campaign`, `products`, `content`, `reviews`. |
| `mode` | `branch` (default): each job runs in its own worktree on `crew/<job-id>`, the person's checkout is never touched, commits stay on the side branch, the worktree is removed when the job ends. `in_place`: the job runs in the folder, commits nothing, and lists the files it changed (for a workspace that is not a product, such as a campaign folder). A folder that is not a git repository runs in place. |
| `github` | True when the repository is already on GitHub. Only then may a cloud runner ever be used for it. |
| `allow_push` | Off by default. When true, and only for `github` projects, crew may push the `crew/` side branch after the repository's leak scan passes (`leak_scan` names the command, default `python3 tests/leak_scan.py` when that file exists). It never pushes anything else. |
| `test` | The test command, run from the project's root. It becomes a done check on every job from this project. |
| `notes` | One or two lines every brief carries (style rules, what never to touch). |
| `allowed_tools` | Extra Claude Code tool patterns, for example `"Bash(npm test:*)"`. |
| `sources` | Where the work comes from, below. |

## Sources

- `{"kind": "plan", "file": "docs/PLAN.md", "max": 20, "tier": "", "runner": "auto"}`: every unticked
  `- [ ]` item (or a `TODO:` line) becomes a job. The tier is guessed from the words when not given: typo,
  rename, lint, wording and the like are `small`; design, architecture, strategy and the like are `top`;
  the rest `fast`. Files named in the item are the job's files. The brief asks the runner to tick the item.
- `{"kind": "evaluator", "dir": "design-review"}` (a path inside the project, or absolute): the latest
  round with verdicts; its fixes ranked the multi-evaluator way (a journey every reviewer flagged first,
  then high severity, then the biggest "if fixed" gap) and batched into one job per journey. Rerun `scan`
  after each new round.
- `{"kind": "tests", "command": "", "timeout": 900}`: runs the project's test command (or `command`); on
  failure, one job "Make the tests pass" with the last 40 lines of output as its context.
- `{"kind": "daily", "id": "inbox", "at": "06:30", "title": "...", "prompt": "...", "tier": "fast",
  "runner": "claude", "done": ["..."], "files": [], "estimate_tokens": 60000}`: one job per day, not before
  `at`. `prompt` is the brief's context; `runner` pins a runner (for example when the job needs a skill only
  one agent has).

## Jobs

A job in `~/.mstack/crew/queue.json` carries: `id`, `project`, `stream`, `title`, `outcome`, `done` (each
`"what::command"` or just `"what"`), `needs` (shared resources such as `chrome`, set when a scan or `add`
sees tests, `run_all`, an evaluator source, or you pass `crew.py add --needs chrome`), `tier`, `estimate_tokens`,
`unattended`, `files`, `runner`, `runner_required` (when true, the job waits for that runner even after it
fails), `source`, `batch`, `context`, `state` (`todo`, `doing`, `done`, `question`, `blocked`, `failed`,
`skipped`), `evidence`, `usage` (tokens, the list price the platform reports for information, the window
after the run), `question` and `default`, `note`, `tries`, `attempts` (each with `runner`, `model`, `started`,
`finished`, `result`, `note`), `retry_after` (when the next automatic try may run). Each attempt keeps its
files under `runs/<job-id>/attempt-<n>/`; `runs/<job-id>/result.json` is always the latest.

## Files in `~/.mstack/crew`

`config.json`, `queue.json`, `state.json` (paused, running, daily counts, digest sent), `usage.json` (the
latest reading per runner), `stop` (the stop file), `tick.lock`, `tick.log`, `runs/`, `worktrees/`, `digests/`.
