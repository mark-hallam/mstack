# Runners: how crew reads usage and runs jobs on each agent

Crew is agent agnostic: the queue, the briefs and the result block are the same whoever does the work. Two
runners are built in; any other agent can take jobs from the same queue.

## What is measured, and how (checked on a real computer)

Crew never guesses usage. Each runner has one honest way to read its plan windows:

| Runner | Where the reading comes from | What it holds |
|---|---|---|
| Claude Code | Every `claude -p ... --output-format stream-json --verbose` run prints a `rate_limit_event`. Its `rate_limit_info.unifiedWindows` lists each window the platform reports (for example `seven_day`, and `five_hour` when it is reported) as `utilization` (0 to 1) and `resetsAt`. Crew reads it from every job it runs, and when no reading is fresh it may make one probe: "Reply with the single word ok" on the smallest model. | The windows the platform reports, their use, their reset time. The `result` line adds the tokens and a list-price figure (for information; a plan is not billed that way). |
| Codex | Every turn appends a `token_count` event with `rate_limits` to the session log at `~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl` (`$CODEX_HOME` honoured, as Codex itself does: the folder in `$CODEX_HOME` when it is set, else `~/.codex`): `primary` is the 5 hour window (`window_minutes` 300), `secondary` the 7 day window (10080), each with `used_percent` and `resets_at`, plus `credits` and `plan_type`. Crew reads the newest log, free, and the log its own runs write. `codex exec --json` prints tokens per turn but not the windows. | Both windows, their use and reset time; whether the account has credits. |

If a reading is unavailable (the program is missing, the log is empty, the event is not printed in some
version), crew goes conservative for that runner: quiet hours only and `conservative.jobs_per_day` jobs,
and says so in `status` and the digest. If a platform changes its format, crew falls back the same way
rather than inventing a number.

A reading is acted on until it is `usage_max_age_minutes` old or its window has reset, then read again.

## How a job runs on each runner

- **Claude Code**: `claude -p "<brief>" --output-format stream-json --verbose --allowedTools <list> --model <tier model>`,
  in the job's worktree. The allowed tools are built from the project: read, edit, search, `git add`,
  `git commit`, `git status`, `git diff`, `git log`, the project's test command and done check commands each
  as the exact command (a rule such as `Bash(python3 tests/run_all.py)` matches that command only, never
  every program that starts with `python3`), and `allowed_tools` from the config. A check command that
  chains or redirects (it holds `&&`, `||`, `;`, `|`, `&`, `>`, `<`, a backtick, `$(` or a new line) is not
  allowed at all. The brief names the commands the agent may run and says the crew runs every done check
  again itself when the agent finishes, so a check the agent cannot run is not a blocker. Nothing else is
  allowed, so a headless run cannot push, and a tool it is not allowed is refused rather than waited for. If the person wants wider permissions for unattended runs, they put the
  flag they accept in `extra_args` themselves.
- **Codex**: `codex exec --json --skip-git-repo-check -C <worktree> -s workspace-write [-m <model>] "<brief>"`.
  The `workspace-write` sandbox keeps writes inside the worktree and blocks the network. It does not limit
  which programs the agent may run inside that sandbox.
- Both run under `caffeinate -i` on macOS, so the Mac stays awake only while the job runs and no setting is
  changed. Both get the same brief: the outcome, the done checks, only the job's files, the context, the
  project notes, the rules, and the result block to end with.

The tier picks the model: `small` for mechanical work, `fast` for most jobs, `top` for design and
architecture. Crew chooses the runner per job: the one the job names, else the readable runner with the
most headroom (a conservative runner comes last).

## Cloud sessions

Crew runs on the person's own computer. A cloud session is allowed only for a project with `github: true`,
only through usage or credits the person already has (Codex reports `credits` in the same reading; a
Claude cloud session runs on the same plan), and never through a paid add-on, extra usage, a paid service
or an API key. There is no built-in cloud runner: to add one, give it a `runners` entry whose `command`
submits the brief and prints the same stream (a `result` line with the reply), and name it in the job's
`runner`. If it cannot report usage, crew treats it as conservative.

## Cursor and other agents

Any agent can work the same queue by hand, under the same rules:

1. `crew.py next --json` gives the job; `crew.py run <job-id> --dry-run` writes its full brief to
   `~/.mstack/crew/runs/<job-id>/prompt.md` and shows the worktree and branch crew would use.
2. Do the work in that worktree (`git worktree add ~/.mstack/crew/worktrees/<job-id> -b crew/<job-id> <branch>`),
   commit with a message starting `crew:`, and end with the JSON result block from the brief.
3. Record it: `crew.py answer` for a question, or mark the job by writing its `state`, `evidence` and `usage`
   into `queue.json` the way `crew_run.py` does. A wrapper that runs the agent's own command line and prints
   a `result` line can be added as a runner, so the tick drives it like the others.

For Cursor's background agents, a `runners` entry whose `command` is the Cursor command line (when it can
run headless and print its reply) makes it a first-class runner. Until it can report usage, it is
conservative by design.
