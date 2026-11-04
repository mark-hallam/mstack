---
name: away-mode
description: Notice by yourself when the person is away from their computer and following from their phone, and present every output in a form they can read there (screenshots, PDFs, files sent to the chat, the key points in the message itself) instead of local paths and open commands they cannot click. On by default. Use whenever you are about to present a file, report, mockup, screenshot, diagram, page or link to the person; whenever they say they are on their phone, out, away, on the train, or back at their desk; and whenever they ask for a screenshot, a PDF, or "send it to me". Also use to check or set away status ("am I away?", "I'm back").
---

# Away mode

The person often starts work on their computer and follows it from their phone (an app that mirrors the
session, push notifications, a remote control feature). From the phone they cannot click a local path,
run an `open` command or look at a file on the computer. They should never have to ask "send me a
screenshot": you notice they are away, and deliver in a form the phone can show.

The tool is `scripts/away.py` (next to this file). Below, `AWAY` means
`python3 <this skill's folder>/scripts/away.py`. Output is JSON unless you add `--text`.

## Before you start (every mStack skill)

- If `~/.mstack/config.json` lists `away-mode` under `"disabled"`, or the person said not to use it for this
  task, present outputs the usual way.
- If `~/.mstack/learned/away-mode.md` exists, read it: it holds this person's accepted improvements, and they
  win over this file.

## 1. Notice: before you present anything, check

Right before presenting a file, report, mockup, screenshot, diagram, page or link, run `AWAY status`. Pass
anything your harness has told you this turn as hints, in its own words:

```
AWAY status --hint "the user follows this session from another device" \
            --hint "push not sent because the user is at the terminal"
```

It answers `{"away": true | false | "unsure", "why": "...", "deliver": "phone" | "local" | "both", ...}`.
The layers, most trusted first:

1. **The person's words win.** "I'm on my phone", "I'm out", "I'm away", "heading out" mean away; "I'm
   back", "at my desk" mean present. When they say one of these, record it at once:
   `AWAY set away` (or `AWAY set back`), or `AWAY heard "<what they said>"` which classifies and records.
   "Away" expires after 8 hours (`--hours N` to change it) or when they say "back". "Back" holds over hints
   and the idle signal for 60 minutes, but not over a locked screen or a sleeping display.
2. **Your harness's hints** (`--hint`): a system note that the person follows from another device or through
   a remote control feature, or that this is a cloud or remote session, means away. A notification tool
   saying the push was "not sent because the user is at the terminal" means they are at the computer.
3. **The machine.** On macOS: keyboard and mouse idle time, whether the screen is locked, and whether the
   display is asleep. On Linux: `loginctl` and `xprintidle` when present. On Windows: the last input time.
   Idle past the threshold (default 10 minutes), a locked screen or a sleeping display mean away.
4. **Unsure** when nothing can be read. Then deliver both ways; it is cheap.

Thresholds live in `~/.mstack/config.json` under `"away"`:
`{"away": {"idle_minutes": 10, "expire_hours": 8, "back_minutes": 60}}`.

## 2. Deliver when away (or unsure)

For each output, make phone-readable copies:

```
AWAY render <file-or-address>            copies go to ~/.mstack/outbox/<date>/ (or --out DIR)
```

- An HTML page becomes a PDF plus a phone-width PNG of the first screen (390 css px wide, light theme), and
  a full-page PNG when the page is short.
- A Markdown file becomes HTML (light theme, system font), then the same as HTML.
- An image is passed through (HEIC becomes PNG).
- A PDF is passed through, with a PNG of its first page where the system can make one.
- A local web app or an address becomes PNG screenshots, desktop and phone, plus a PDF.

It uses headless Google Chrome or Chromium when present and falls back to the system's own tools. If
nothing can render, it says so plainly in `notes`: then put the essential content in the message itself.

Then, in this order of preference:

1. **Send the files to the chat** with whatever "send a file to the person" tool your harness has. In Claude
   Code that is SendUserFile, which renders images and PDFs on the phone. Send the PNG first (it shows
   inline), then the PDF.
2. If there is no such tool, **publish a private copy** the person can open on the phone, if your harness
   offers private hosting (for example a private artifact), and give the link.
3. If neither, **put the essential content in the message itself**: the headings, the numbers, the verdict.

## 3. The rules while away

- **Never end with only a local path or an `open` command.** They cannot use it. Mention the path once,
  after the phone-readable copies, so they can find the file later.
- **Always put the 3 to 5 key points in the reply text**, and keep the reply short for a small screen:
  short lines, no wide tables, no long code blocks.
- **Show light-theme screenshots** (the renderer defaults to light).
- **Pair with ping-me**: the notification says the files are in the chat, for example
  "Done: design report in the chat (PNG + PDF), 3 fixes proposed".
- **Unsure**: do the phone delivery and also give the local path or `open` command.
- **When they are back** (they say so, or `AWAY status` reads them at the computer), return to normal:
  local paths and `open` commands are fine again.

## After

Record privately how it went: `python3 <mstack skill folder>/scripts/mstack.py log away-mode --outcome reached`
(add `--correction "..."` if the person had to ask for a screenshot or PDF anyway, or was wrongly treated as
away). The mstack skill sits next to this one.
