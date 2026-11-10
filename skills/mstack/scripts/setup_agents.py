"""setup claude-hooks and setup cursor: show the change first, make it only with --write, and undo it with --remove.

Python 3.9 or later, standard library only. Each function returns a dict (ok, message, and the details) that
mstack.py prints as text or as JSON.
"""
import json
import os
import shlex

import notify as notes
import setup_files as files
from mbase import Fail, home

CURSOR_MARK = "description: mStack skills switch on by themselves when relevant"


def hook_command(tool):
    return "python3 %s ping hook" % shlex.quote(tool)


def is_ours(group):
    return any("mstack.py" in h.get("command", "") and "ping hook" in h.get("command", "")
               for h in group.get("hooks", []) if isinstance(h, dict))


def load_settings(path):
    """The settings object, {} when there is no file. A file that is not a JSON object stops with a plain line."""
    text = files.read(path)
    if text is None:
        return {}
    try:
        settings = json.loads(text)
        hooks = settings.get("hooks", {}) if isinstance(settings, dict) else None
        if hooks is None or not isinstance(hooks, dict) or not all(
                isinstance(g, list) and all(isinstance(x, dict) for x in g) for g in hooks.values()):
            raise ValueError("unexpected shape")
        return settings
    except ValueError:
        raise Fail("Could not read %s as Claude Code settings (it is not valid JSON, or not shaped as expected), "
                   "so it was left untouched." % path, 1, file=path)


def setup_claude(args):
    given = args.settings or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    path = files.real(given)
    entry = {"type": "command", "command": hook_command(home("bin", "mstack.py")), "async": True}
    want = {"Notification": {"matcher": "permission_prompt|idle_prompt|elicitation_dialog|agent_needs_input",
                             "hooks": [entry]},
            "Stop": {"hooks": [entry]}}
    settings = load_settings(path)
    existed = os.path.exists(path)
    hooks = settings.setdefault("hooks", {})
    changed = []
    for event, group in want.items():
        groups = hooks.setdefault(event, [])
        mine = [g for g in groups if is_ours(g)]
        if args.remove:
            for g in mine:
                groups.remove(g)
                changed.append("removed %s" % event)
            if not groups:
                hooks.pop(event)
        elif not mine:
            groups.append(group)
            changed.append("added %s" % event)
    if not hooks:
        settings.pop("hooks")
    policy = notes.text_policy()
    base = {"ok": True, "target": "claude-hooks", "file": path, "remove": bool(args.remove), "notification_text": policy}
    if not args.write:
        preview = json.dumps({"hooks": dict((e, want[e]) for e in want)}, indent=2)
        return dict(base, written=False, would_change=changed, message=(
            "Would %s these Claude Code hooks in %s:\n%s\n%s\nAsk the person; then run again with --write." % (
                "remove" if args.remove else "add", files.shown(given), preview, policy)))
    if not changed:
        return dict(base, written=False, changed=[], message="Nothing to change in %s." % path)
    if not args.remove:
        files.stable_copy()
    backup = None
    deleted = bool(args.remove and existed and not settings and not os.path.exists(path + ".mstack-backup"))
    if deleted:                                                            # mStack made the file and nothing else is in it
        os.remove(path)
    else:
        backup = files.keep_backup(path)
        files.write(path, json.dumps(settings, indent=2) + "\n")
    message = ("%s; %s held nothing else, so it was deleted" % (", ".join(changed), path)) if deleted else (
        "%s in %s (backup: %s.mstack-backup)" % (", ".join(changed), path, path))
    return dict(base, written=True, changed=changed, backup=backup, deleted=deleted, message=message)


def setup_cursor(args, routing):
    project = os.path.abspath(args.project or ".")
    given = os.path.join(project, ".cursor", "rules", "mstack.mdc")
    path = files.real(given)
    backup = path + ".mstack-backup"
    body = "---\n%s\nalwaysApply: true\n---\n\n%s\n" % (CURSOR_MARK, routing)
    base = {"ok": True, "target": "cursor", "file": path, "remove": bool(args.remove)}
    if args.remove:
        current = files.read(path)
        if current is None:
            return dict(base, written=False, message="Nothing to remove: %s does not exist." % given)
        if CURSOR_MARK not in current:
            raise Fail("%s is not the rule mStack wrote, so it was left untouched." % path, 1, file=path)
        restore = os.path.exists(backup)
        if not args.write:
            return dict(base, written=False, message="Would %s %s.\nAsk the person; then run again with --write." % (
                "put back the file that was there before in" if restore else "delete", files.shown(given)))
        if restore:
            files.write(path, files.read(backup))
            os.remove(backup)
        else:
            os.remove(path)
            for d in (os.path.dirname(path), os.path.dirname(os.path.dirname(path))):
                try:
                    os.rmdir(d)                         # only if nothing else is in it
                except OSError:
                    break
        return dict(base, written=True, message="%s %s" % ("restored" if restore else "removed", path))
    if not args.write:
        return dict(base, written=False, message="Would write %s:\n\n%s\nAsk the person; then run again with --write." % (
            files.shown(given), body))
    current = files.read(path)
    if current is not None and CURSOR_MARK not in current:
        files.keep_backup(path)                         # a rule of the person's own with this name: keep it for --remove
    files.write(path, body)
    return dict(base, written=True, message="wrote %s" % path)
