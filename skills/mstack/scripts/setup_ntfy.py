"""setup ntfy: opt in to a free phone push service. Shows the change, writes it only with --write, then tests it.

Python 3.9 or later, standard library only.
"""
import re
import secrets
import urllib.parse

import notify as notes
from mbase import DEFAULTS, Fail, home, load_config, save_config

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def check_server(server):
    """https is required, except for a server on this computer. Returns the server without a trailing slash."""
    parts = urllib.parse.urlsplit(server)
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise Fail("The ntfy server must be a web address such as https://ntfy.sh, with no user name or password.", 1)
    if parts.scheme != "https" and host not in LOCAL_HOSTS:
        raise Fail("The ntfy server must start with https:// (plain http is only allowed for localhost, 127.0.0.1 or "
                   "[::1]), because your pings would cross the internet unprotected.", 1)
    return server.rstrip("/")


def setup_ntfy(args):
    cfg = load_config()
    current = cfg["ping"].get("ntfy_topic") or ""
    path = home("config.json")
    if args.remove:
        if not args.write:
            return {"ok": True, "target": "ntfy", "remove": True, "written": False, "file": path, "message": (
                "Would remove the ntfy topic from %s. Ask the person; then run again with --write." % path)}
        cfg["ping"]["ntfy_topic"] = ""
        save_config(cfg)
        return {"ok": True, "target": "ntfy", "remove": True, "written": True, "file": path,
                "message": "removed the ntfy topic from %s" % path}
    topic = args.topic or current or "mstack-" + secrets.token_urlsafe(18)
    server = check_server(args.server or cfg["ping"].get("ntfy_server") or DEFAULTS["ping"]["ntfy_server"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic):
        raise Fail("A topic is 8 to 64 letters, digits, - or _ (no spaces), and long enough that nobody can guess it.", 1)
    target = "%s/%s" % (server, topic)
    policy = notes.text_policy(cfg, ntfy=target)
    sends_reply = notes.reply_goes_to_ntfy(cfg, ntfy=target)
    steps = ("What this does: every ping is also sent, as plain text, to %s. Anyone who knows the topic name can read "
             "it, so it is long and random and must stay private. Never put passwords or private details in a ping.\n"
             "%s\n"
             "1. On the phone, install the ntfy app (free, open source) and subscribe to the topic: %s\n"
             "2. This writes to %s: {\"ping\": {\"ntfy_topic\": \"%s\", \"ntfy_server\": \"%s\"}}\n"
             "3. Then a test ping is sent, so the person can confirm it arrived." % (target, policy, topic, path, topic, server))
    base = {"ok": True, "target": "ntfy", "remove": False, "file": path, "topic": topic, "server": server,
            "notification_text": policy, "reply_text_sent_to_ntfy": sends_reply}
    if not args.write:
        return dict(base, written=False, message="Would set up phone pings through ntfy.\n%s\nAsk the person; then run again with --write." % steps)
    cfg["ping"]["ntfy_topic"] = topic
    cfg["ping"]["ntfy_server"] = server
    save_config(cfg)
    sent = notes.notify("mStack: phone pings are on. This came through ntfy.", "mStack")
    return dict(base, written=True, test_ping=sent, message="written to %s (topic %s)\ntest ping sent: %s" % (
        path, topic, ", ".join(sent)))
