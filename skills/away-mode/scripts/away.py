#!/usr/bin/env python3
"""Away mode: is the person at this computer or following from their phone, and how to deliver to them.

Python 3.9 or later, standard library only. The person's own words are kept in ~/.mstack/away.json (or
$MSTACK_HOME/away.json); thresholds come from the "away" section of ~/.mstack/config.json.

  status [--hint TEXT ...] [--text]      {"away": true|false|"unsure", "why": ..., "signals": ..., "deliver": ...}
  set away|back [--hours N]              record what the person said ("I'm on my phone" / "I'm back")
  heard "<what the person said>"         classify their words and record them if they say away or back
  render <file-or-url> [--out DIR]       phone-readable copies (PDF, PNG) in the outbox; see away_render.py
  outbox                                 where the copies go

How the answer is reached, most trusted first:
  1. The person's words: "away" wins until it expires (default 8 hours) or they say "back". "back" wins over
     hints and the idle signal for a while (default 60 minutes), but not over a locked screen or a sleeping
     display (locking is deliberate).
  2. The agent's hints (--hint): a note that the person follows from another device or Remote Control, a
     cloud session, or a notification tool saying the push was not sent because they are at the terminal.
  3. The machine: keyboard and mouse idle past a threshold (default 10 minutes) means away; recent input
     means present. (A locked screen or sleeping display means away, checked right after the person's "away".)
  4. Nothing readable: "unsure". Deliver both ways then; it is cheap.
"""
import argparse
import datetime
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {"idle_minutes": 10, "expire_hours": 8, "back_minutes": 60, "phone_width": 390, "scale": 2}

AWAY_WORDS = ("on my phone", "on the phone", "from my phone", "on my mobile", "on my watch", "i'm out", "im out",
              "i am out", "i'm away", "im away", "i am away", "away from my desk", "not at my desk", "heading out",
              "going out", "leaving now", "on the train", "on the road", "remote control")
BACK_WORDS = ("i'm back", "im back", "i am back", "at my desk", "at the desk", "at my mac", "at the mac",
              "at my computer", "back at my", "at the keyboard", "in front of the screen", "at my laptop")
AWAY_HINTS = ("remote control", "remote-control", "another device", "other device", "from their phone", "on the phone",
              "mobile", "cloud session", "cloud", "remote session", "web session", "follows from")
HERE_HINTS = ("at the terminal", "at-terminal", "at the keyboard", "at the computer", "at their desk", "at-desk")


# ---------------------------------------------------------------- home and config

def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, *parts)


def config():
    cfg = dict(DEFAULTS)
    path = home("config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                mine = json.load(fh).get("away", {})
            if isinstance(mine, dict):
                cfg.update(mine)
        except ValueError:
            pass
    return cfg


def now():
    return datetime.datetime.now()


def stamp(dt):
    return dt.isoformat(timespec="seconds")


def parse(text):
    return datetime.datetime.fromisoformat(text)


# ---------------------------------------------------------------- 1. the person's words

def words_record():
    path = home("away.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


def words_signal(cfg, at=None):
    """What the person last said, and whether it still counts."""
    rec = words_record()
    if not rec or rec.get("state") not in ("away", "back"):
        return {"state": None}
    at = at or now()
    try:
        said = parse(rec["at"])
    except (KeyError, ValueError):
        return {"state": None}
    out = {"state": rec["state"], "at": rec["at"], "active": False}
    if rec["state"] == "away":
        try:
            until = parse(rec.get("until") or "")
        except ValueError:
            until = said + datetime.timedelta(hours=float(cfg["expire_hours"]))
        out["until"] = stamp(until)
        out["active"] = at < until
        if not out["active"]:
            out["note"] = "expired"
    else:
        grace = said + datetime.timedelta(minutes=float(cfg["back_minutes"]))
        out["until"] = stamp(grace)
        out["active"] = at < grace
        if not out["active"]:
            out["note"] = "grace over; the machine decides again"
    return out


def set_words(state, hours=None, cfg=None):
    cfg = cfg or config()
    os.makedirs(home(), exist_ok=True)
    rec = {"state": state, "at": stamp(now()), "source": "words"}
    if state == "away":
        rec["until"] = stamp(now() + datetime.timedelta(hours=float(hours or cfg["expire_hours"])))
    with open(home("away.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
        fh.write("\n")
    return rec


def classify_words(text):
    """'away', 'back' or None from what the person said. 'back' wins when both appear ("I was out, I'm back")."""
    t = " ".join(text.lower().replace("’", "'").split())
    if any(w in t for w in BACK_WORDS):
        return "back"
    if any(w in t for w in AWAY_WORDS):
        return "away"
    return None


# ---------------------------------------------------------------- 2. the agent's hints

def classify_hint(text):
    t = " ".join(text.lower().split())
    if any(w in t for w in HERE_HINTS):
        return "present"
    if any(w in t for w in AWAY_HINTS):
        return "away"
    return None


def hints_signal(hints):
    out = []
    for h in hints or []:
        out.append({"hint": h, "means": classify_hint(h)})
    return out


# ---------------------------------------------------------------- 3. the machine

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return b""


def machine_macos():
    sig = {"source": "macos", "idle_seconds": None, "locked": None, "display_asleep": None}
    m = re.search(rb'"HIDIdleTime" = (\d+)', run(["ioreg", "-c", "IOHIDSystem"]))
    if m:
        sig["idle_seconds"] = int(m.group(1)) / 1e9
    try:
        root = plistlib.loads(run(["ioreg", "-n", "Root", "-d1", "-a"]) or b"")
        users = [u for u in root.get("IOConsoleUsers", []) if u.get("kCGSSessionOnConsoleKey")]
        if users:
            sig["locked"] = bool(any(u.get("CGSSessionScreenIsLocked") for u in users))
    except Exception:
        pass
    power = run(["ioreg", "-r", "-d1", "-c", "AppleCLCD2"]).decode("utf-8", "replace")
    states = re.findall(r'"CurrentPowerState"=(\d+)', power)
    if states:
        sig["display_asleep"] = all(s == "0" for s in states)
    else:
        power = run(["ioreg", "-r", "-d1", "-c", "IODisplayWrangler"]).decode("utf-8", "replace")
        states = re.findall(r'"CurrentPowerState"=(\d+)', power)
        if states:
            sig["display_asleep"] = int(states[0]) < 4
    return sig


def machine_linux():
    sig = {"source": "linux", "idle_seconds": None, "locked": None, "display_asleep": None}
    if shutil.which("xprintidle"):
        out = run(["xprintidle"]).decode("ascii", "replace").strip()
        if out.isdigit():
            sig["idle_seconds"] = int(out) / 1000.0
    if shutil.which("loginctl"):
        sid = os.environ.get("XDG_SESSION_ID") or ""
        if not sid:
            out = run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Display", "--value"])
            sid = out.decode("ascii", "replace").strip()
        if sid:
            out = run(["loginctl", "show-session", sid, "-p", "IdleHint", "-p", "LockedHint"]).decode("ascii", "replace")
            if "LockedHint=" in out:
                sig["locked"] = "LockedHint=yes" in out
            if sig["idle_seconds"] is None and "IdleHint=yes" in out:
                sig["idle_hint"] = True
    return sig


def machine_windows():
    sig = {"source": "windows", "idle_seconds": None, "locked": None, "display_asleep": None}
    ps = ("Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class LI {"
          " [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }"
          " [DllImport(\"user32.dll\")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii); }';"
          " $l = New-Object LI+LASTINPUTINFO; $l.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($l);"
          " [LI]::GetLastInputInfo([ref]$l) | Out-Null; ([Environment]::TickCount - $l.dwTime) / 1000")
    out = run(["powershell", "-NoProfile", "-Command", ps], timeout=20).decode("ascii", "replace").strip()
    try:
        sig["idle_seconds"] = float(out.splitlines()[-1])
    except (ValueError, IndexError):
        pass
    out = run(["powershell", "-NoProfile", "-Command", "(Get-Process LogonUI -ErrorAction SilentlyContinue) -ne $null"],
              timeout=20).decode("ascii", "replace").strip().lower()
    if out in ("true", "false"):
        sig["locked"] = out == "true"
    return sig


def machine_signal():
    """The machine's own signals. MSTACK_AWAY_MACHINE (JSON text or a file of it) stands in for tests."""
    fake = os.environ.get("MSTACK_AWAY_MACHINE")
    if fake:
        try:
            if os.path.exists(fake):
                with open(fake, encoding="utf-8") as fh:
                    fake = fh.read()
            sig = {"source": "stand-in", "idle_seconds": None, "locked": None, "display_asleep": None}
            sig.update(json.loads(fake))
            return sig
        except ValueError:
            return {"source": "stand-in", "idle_seconds": None, "locked": None, "display_asleep": None}
    if sys.platform == "darwin":
        return machine_macos()
    if sys.platform.startswith("linux"):
        return machine_linux()
    if os.name == "nt":
        return machine_windows()
    return {"source": sys.platform, "idle_seconds": None, "locked": None, "display_asleep": None}


# ---------------------------------------------------------------- the verdict

def minutes(seconds):
    return "%d minute%s" % (int(seconds // 60), "" if int(seconds // 60) == 1 else "s")


def decide(words, hints, machine, cfg):
    """Return (away, why). away is True, False or "unsure"."""
    if words.get("active") and words["state"] == "away":
        return True, "the person said they were away at %s (counts until %s)" % (words["at"], words["until"])
    if machine.get("locked"):
        return True, "the screen is locked"
    if machine.get("display_asleep"):
        return True, "the display is asleep"
    if words.get("active") and words["state"] == "back":
        return False, "the person said they were back at %s (holds until %s unless the screen locks)" % (words["at"], words["until"])
    means = [h["means"] for h in hints if h["means"]]
    if "away" in means and "present" not in means:
        return True, "the agent's own hints say the person follows from another device or a remote session"
    if "present" in means and "away" not in means:
        return False, "the agent's own hints say the person is at the computer (for example a push was not sent because they are at the terminal)"
    idle = machine.get("idle_seconds")
    threshold = float(cfg["idle_minutes"]) * 60
    if idle is not None:
        if idle >= threshold:
            return True, "no keyboard or mouse for %s (threshold %s)" % (minutes(idle), minutes(threshold))
        return False, "keyboard or mouse used %s ago" % minutes(idle)
    if machine.get("idle_hint"):
        return True, "the login session reports the user idle"
    if machine.get("locked") is False and machine.get("display_asleep") is False:
        return "unsure", "the screen is on and unlocked but idle time could not be read"
    return "unsure", "no readable signal: no words from the person, no hints, and the machine's idle and lock state could not be read"


def status(hints=None, cfg=None):
    cfg = cfg or config()
    words = words_signal(cfg)
    hint_rows = hints_signal(hints)
    machine = machine_signal()
    away, why = decide(words, hint_rows, machine, cfg)
    deliver = "phone" if away is True else ("both" if away == "unsure" else "local")
    return {"away": away, "why": why, "deliver": deliver,
            "signals": {"words": words, "hints": hint_rows, "machine": machine},
            "config": {"idle_minutes": cfg["idle_minutes"], "expire_hours": cfg["expire_hours"],
                       "back_minutes": cfg["back_minutes"]},
            "next": {"phone": "render each output with away.py render, send the copies to the chat, put the key points in the reply",
                     "both": "do the phone delivery and also give the local path or open command",
                     "local": "present as usual: local paths and open commands are fine"}[deliver]}


# ---------------------------------------------------------------- commands

def cmd_status(args):
    s = status(args.hint)
    if args.text:
        label = {True: "away", False: "present", "unsure": "unsure"}[s["away"]]
        print("%s: %s. Deliver: %s." % (label, s["why"], s["deliver"]))
    else:
        print(json.dumps(s, indent=2))


def cmd_set(args):
    rec = set_words(args.state, args.hours)
    print(json.dumps({"ok": True, "recorded": rec, "file": home("away.json")}, indent=2))


def cmd_heard(args):
    state = classify_words(args.text)
    out = {"heard": args.text, "means": state}
    if state:
        out["recorded"] = set_words(state)
    print(json.dumps(out, indent=2))


def cmd_render(args):
    sys.path.insert(0, HERE)
    import away_render
    result = away_render.render(args.target, out_dir=args.out, cfg=config(), name=args.name)
    if args.text:
        for f in result["files"]:
            print("%s  %d bytes  %s" % (f["path"], f["bytes"], f["what"]))
        for n in result["notes"]:
            print("note: %s" % n)
    else:
        print(json.dumps(result, indent=2))
    sys.exit(0 if result["files"] else 1)


def cmd_outbox(args):
    sys.path.insert(0, HERE)
    import away_render
    print(away_render.outbox())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status", help="is the person away? JSON by default")
    s.add_argument("--hint", action="append", default=[],
                   help="something the harness told you, for example 'the user follows from another device' or "
                        "'not sent because the user is at the terminal' (repeatable)")
    s.add_argument("--text", action="store_true", help="one line instead of JSON")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("set", help="record the person's words")
    s.add_argument("state", choices=("away", "back"))
    s.add_argument("--hours", type=float, help="away: how long it counts for (default from config, 8)")
    s.set_defaults(fn=cmd_set)
    s = sub.add_parser("heard", help="classify what the person said and record it if it says away or back")
    s.add_argument("text")
    s.set_defaults(fn=cmd_heard)
    s = sub.add_parser("render", help="make phone-readable copies of a file or address")
    s.add_argument("target", help="an HTML, Markdown, image or PDF file, or an http(s) address")
    s.add_argument("--out", help="folder for the copies (default: the outbox)")
    s.add_argument("--name", help="base name for the copies (default: the file's own name)")
    s.add_argument("--text", action="store_true", help="one line per file instead of JSON")
    s.set_defaults(fn=cmd_render)
    sub.add_parser("outbox", help="print the outbox folder").set_defaults(fn=cmd_outbox)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
