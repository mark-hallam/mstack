---
name: ping-me
description: Notify the person on their phone and watch, without being asked, whenever you need their decision or input, or a task they asked for is complete or blocked. On by default, in every session, so they can step away while you work. Use whenever you are about to ask the person a question, wait for their approval, stop because something only they can do, or finish or give up on a task they gave you. Also use to set up notifications for Claude Code, Codex, Cursor or a phone service, or when the person says "ping me", "let me know when it's done", "notify me", "no pings" or "stop notifying me".
---

# Ping me

The person should never have to watch the screen to know when you need them. Whenever you need their
decision or input, or a task they asked for is complete or blocked, tell them on their phone and watch,
straight away and without being asked.

## Before you start (every mStack skill)

- If `~/.mstack/config.json` lists `ping-me` under `"disabled"`, or the person said "no pings" (or similar)
  for this task, do not notify.
- If `~/.mstack/learned/ping-me.md` exists, read it: it holds this person's accepted improvements, and they
  win over this file.

## When to ping

- **Their decision or input is needed**: a question only they can answer, an approval, a choice between
  options. Batch every open question into one ping, not one ping each.
- **Something only they can do**: sign in, pay, press a button in an app you cannot reach.
- **Done**: a task they asked for is complete and verified.
- **Blocked**: you stopped and cannot continue without them.

Not for routine progress, and not when they are clearly at the screen answering you right now.

## How to write it

One line, under 200 characters, leading with what they would act on:
"Need your OK to publish the site: 2 options in the chat" or "Done: report ready, every journey 10/10".
Never put passwords, tokens or private details in a notification.

## How to send it

Use the best channel your agent has, in this order:

1. **Claude Code**: the PushNotification tool. With the Claude desktop app's notifications on (its
   "question", "permission request" and "task complete" notifications) and Remote Control connected,
   these reach the person's phone and watch.
2. **Codex, Cursor and other agents**: their own notification, if they have one. Otherwise the portable
   tool: `python3 <mstack skill folder>/scripts/mstack.py ping "<message>"` (the mstack skill sits next to
   this one). It shows a desktop notification on macOS (osascript), Linux (notify-send) or Windows, and
   phones that mirror the computer's notifications show it too.
3. **A phone service** (optional, off by default, because it sends the text to a third party): the person
   can add their own private ntfy topic to `~/.mstack/config.json`:
   `{"ping": {"ntfy_topic": "<a long private name>"}}` and install the ntfy app. Only suggest it; never turn
   it on yourself.

## Making it reliable (platform level, with the person's yes)

The rule above depends on you remembering. These make the platform ping even if you forget. Show the
change, ask the person, and only then add `--write`:

- **Claude Code hooks**: `mstack.py setup claude-hooks` adds a `Notification` hook (Claude is waiting for
  permission or input) and a `Stop` hook (a turn finished) to `~/.claude/settings.json`, both raising a
  desktop notification. `--remove` takes them out. If the desktop app already notifies the person, these
  can double up: ask which they prefer.
- **Codex**: `mstack.py setup codex` adds a `notify` program to `~/.codex/config.toml`, which Codex runs
  when a turn completes. It never replaces a `notify` setting the person already has.
- **Cursor and others**: `mstack.py setup cursor --project <folder>` adds the rule as an always-applied
  project rule.

`mstack.py ping test` sends a test notification.

## After

Record privately how it went: `python3 <mstack skill folder>/scripts/mstack.py log ping-me --outcome reached`
(add `--correction "..."` if the person said a ping was unwanted or missing).
