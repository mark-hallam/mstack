"""ping me: send a notification, and the hook and Codex paths that send one when an agent finishes.

Python 3.9 or later, standard library only. Reply text is private by default: a hook notification says that a turn
finished and names the project folder, and carries none of the agent's words unless the person sets
"notify_reply_text": true in config.json. An explicit `ping "<message>"` always sends the message it is given.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

from mbase import is_on, load_config, say

REPLY_CHARS = 160


def reply_text_on(cfg=None):
    return (cfg or load_config()).get("notify_reply_text") is True


def ntfy_target(cfg=None):
    """The ntfy address pings go to, or "" when ntfy is off."""
    ping = (cfg or load_config())["ping"]
    return "%s/%s" % ((ping.get("ntfy_server") or "https://ntfy.sh").rstrip("/"), ping["ntfy_topic"]) if ping.get("ntfy_topic") else ""


def text_policy(cfg=None, ntfy=None):
    """Plain words for what a hook notification says and where it goes. ntfy overrides the configured address."""
    cfg = cfg or load_config()
    where = "the desktop notification on this computer" if cfg["ping"].get("desktop", True) else "nowhere on this computer"
    target = ntfy if ntfy is not None else ntfy_target(cfg)
    if reply_text_on(cfg):
        text = ("A notification from a hook or from Codex carries the first %d characters of the agent's reply "
                "(notify_reply_text is true in %s)." % (REPLY_CHARS, "config.json"))
        if target:
            text += " Goes to %s and, because ntfy is on, that reply text is sent to the ntfy server at %s, a third party." % (
                where, target)
        else:
            text += " Goes to %s only." % where
        return text
    text = ("A notification from a hook or from Codex says only \"Turn finished in <project folder>\" (or \"Waiting for you "
            "in <project folder>\"). No reply text is included: set \"notify_reply_text\": true in config.json to add the "
            "first %d characters of the reply. Goes to %s" % (REPLY_CHARS, where))
    return text + (" and to the ntfy server at %s (the folder name only)." % target if target else " only.")


def reply_goes_to_ntfy(cfg=None, ntfy=None):
    cfg = cfg or load_config()
    return reply_text_on(cfg) and bool(ntfy if ntfy is not None else ntfy_target(cfg))


def notify(message, title="mStack"):
    """Notify the person: desktop by default, plus their own phone service only if they set one up."""
    cfg = load_config()
    if not is_on("ping-me", cfg):
        return ["off"]
    message = " ".join(str(message).split())[:200]
    sent = []
    override = os.environ.get("MSTACK_NOTIFY_COMMAND")          # for tests and unusual systems
    env = dict(os.environ, MSTACK_TITLE=title, MSTACK_MESSAGE=message)
    if override:
        subprocess.run(override, shell=True, env=env, timeout=20, stdout=subprocess.DEVNULL)
        sent.append("command")
    elif cfg["ping"].get("desktop", True):
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            "display notification (item 2 of argv) with title (item 1 of argv) sound name \"Glass\"",
                            "-e", "end run", title, message], capture_output=True, timeout=20)
            sent.append("desktop")
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=20)
            sent.append("desktop")
        elif os.name == "nt" and shutil.which("powershell"):
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                  "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
                  "$n.Visible = $true; $n.ShowBalloonTip(8000, $env:MSTACK_TITLE, $env:MSTACK_MESSAGE, 'Info')")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, timeout=20)
            sent.append("desktop")
    target = ntfy_target(cfg)
    if target:                                                   # opt in only: this sends the text to a third party
        req = urllib.request.Request(target, data=message.encode("utf-8"),
                                     headers={"Title": title.encode("ascii", "replace").decode()})
        try:
            urllib.request.urlopen(req, timeout=10)
            sent.append("ntfy")
        except Exception as e:
            sent.append("ntfy failed: %s" % e)
    if not sent:
        sent.append("printed")
    return sent


def reply_or(text, fallback):
    """The agent's words (first 160 characters) when the person allowed them; otherwise the plain fallback."""
    if reply_text_on():
        text = " ".join((text or "").split())[:REPLY_CHARS]
        if text:
            return text
    return fallback


def finished(where, default_where):
    return "Turn finished in %s" % where if where != default_where else "Turn finished"


def parse(text):
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def hook_event(event):
    """Claude Code's Notification and Stop hooks. Returns what was sent, or None for other events."""
    where = os.path.basename(event.get("cwd") or "") or "Claude Code"
    kind = event.get("hook_event_name")
    if kind == "Notification":
        waiting = "Waiting for you in %s" % where if where != "Claude Code" else "Waiting for you"
        return notify(reply_or(event.get("message"), waiting), "Claude needs you: %s" % where)
    if kind == "Stop":
        return notify(reply_or(event.get("last_assistant_message"), finished(where, "Claude Code")),
                      "Claude finished: %s" % where)
    return None


def codex_event(event):
    if event.get("type") != "agent-turn-complete":
        return None
    where = os.path.basename(event.get("cwd") or "") or "Codex"
    return notify(reply_or(event.get("last-assistant-message"), finished(where, "Codex")), "Codex finished: %s" % where)


def chain_original(also, extra):
    """Run the notify program the person already had, with the same event."""
    try:
        original = json.loads(also)
    except ValueError:
        return
    if isinstance(original, list) and original and all(isinstance(x, str) for x in original):
        try:
            subprocess.run(original + [extra or "{}"], timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass


def cmd_ping(args):
    if args.message == "hook":
        sent = hook_event(parse(sys.stdin.read()))
    elif args.message == "codex-event":
        sent = codex_event(parse(args.extra))
        if args.also:
            chain_original(args.also, args.extra)
    elif args.message == "test":
        sent = notify("mStack test: notifications reach you.", "mStack")
        cfg = load_config()
        say(args, {"ok": True, "sent": sent, "notification_text": text_policy(cfg),
                   "reply_text_sent_to_ntfy": reply_goes_to_ntfy(cfg)},
            "sent: %s\n%s" % (", ".join(sent), text_policy(cfg)))
        return
    else:
        sent = notify(args.message, args.title)
        if sent == ["printed"] and not getattr(args, "json", False):
            print("%s: %s" % (args.title, " ".join(args.message.split())[:200]))
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "sent": sent or []}, indent=2))
    elif sent and args.message not in ("hook", "codex-event"):
        print("sent: %s" % ", ".join(sent))
