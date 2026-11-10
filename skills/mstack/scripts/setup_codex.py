"""setup codex: mStack's routing block in Codex's AGENTS.md and a notify line in config.toml, added or taken out.

Python 3.9 or later, standard library only. Add and remove are exact opposites: a notify program the person
already had is chained (and its original line kept in a comment), and --remove puts that line back as it was.
"""
import json
import os
import re

import notify as notes
import setup_files as files
from mbase import home

NOTIFY_RE = re.compile(r"(?m)^[ \t]*notify[ \t]*=[ \t]*(.*)$")
ADDED = "# mStack ping me: notify when a Codex turn finishes"
KEPT = "# mstack-original-notify: "
OLD_CHAIN = "# mStack chained the notify program that was here: "


def top_notify(text):
    """The top-level notify line of a config.toml (before any [section]), or None."""
    return NOTIFY_RE.search(re.split(r"(?m)^\s*\[", text, maxsplit=1)[0])


def as_program(raw):
    try:
        value = json.loads(raw.split("#")[0].strip())
    except ValueError:
        return None
    return value if isinstance(value, list) and value and all(isinstance(x, str) for x in value) else None


def remove_notify(text):
    """(new text, the line put back or None). Takes out mStack's notify line and what mStack wrote around it."""
    m = top_notify(text)
    if not m or "mstack.py" not in m.group(0):
        return None, None
    lines = text.split("\n")
    i = text[:m.start()].count("\n")
    prev = lines[i - 1] if i else ""
    if prev == ADDED:
        del lines[i - 1:i + 2 if i + 1 < len(lines) and lines[i + 1] == "" else i + 1]
        return "\n".join(lines), None
    restored = None
    if prev.startswith(KEPT):
        restored = prev[len(KEPT):]
    elif prev.startswith(OLD_CHAIN):                      # written by 0.7.1: rebuild the line from the chained program
        mine = as_program(m.group(1))
        if mine and "--also" in mine and mine.index("--also") + 1 < len(mine):
            program = as_program(mine[mine.index("--also") + 1])
            restored = "notify = %s" % json.dumps(program) if program else None
    if restored is not None:
        lines[i - 1:i + 1] = [restored]
    else:
        del lines[i]
    return "\n".join(lines), restored


def setup_codex(args, routing):
    given_cfg = args.codex_config or os.path.join(os.path.expanduser("~"), ".codex", "config.toml")
    given_agents = os.path.join(os.path.dirname(given_cfg), "AGENTS.md")
    cfg_path, agents_path = files.real(given_cfg), files.real(given_agents)
    tool = home("bin", "mstack.py")
    line = 'notify = ["python3", %s, "ping", "codex-event"]' % json.dumps(tool)
    text = files.read(cfg_path) or ""
    agents = files.read(agents_path)
    block = "%s\n## mStack\n\n%s\n%s" % (files.START, routing, files.END)
    has_notify = top_notify(text)
    ours = bool(has_notify) and "mstack.py" in has_notify.group(0)
    policy = notes.text_policy()
    base = {"ok": True, "target": "codex", "remove": bool(args.remove), "config": cfg_path, "agents": agents_path,
            "notification_text": policy}
    if args.remove:
        return remove(args, base, given_cfg, given_agents, text, agents)
    previous = None                                          # the person's own notify program, chained if we can read it
    if has_notify and not ours:
        previous = as_program(has_notify.group(1))
        if previous:
            line = 'notify = ["python3", %s, "ping", "codex-event", "--also", %s]' % (json.dumps(tool), json.dumps(json.dumps(previous)))
    if not args.write:
        what = "add to %s (at the top, before any [section])" % files.shown(given_cfg)
        if previous:
            what = "replace the notify line in %s with one that runs mStack's ping and then your own program (%s)" % (
                files.shown(given_cfg), " ".join(previous))
        elif has_notify and not ours:
            what = ("leave the notify line in %s alone (it could not be read as a list of strings; chain it yourself) "
                    "and would otherwise add" % files.shown(given_cfg))
        return dict(base, written=False, message=(
            "Would %s:\n  %s\nand put mStack's routing block in %s (Codex reads that file in every session):\n\n%s\n\n%s\n"
            "Ask the person; then run again with --write." % (what, line, files.shown(given_agents), block, policy)))
    files.stable_copy()
    notes_out = []
    if not has_notify:
        files.keep_backup(cfg_path)
        files.write(cfg_path, "%s\n%s\n\n%s" % (ADDED, line, text))
        notes_out.append("added notify to %s" % cfg_path)
    elif previous:
        files.keep_backup(cfg_path)
        files.write(cfg_path, text.replace(has_notify.group(0), "%s%s\n%s" % (KEPT, has_notify.group(0), line), 1))
        notes_out.append("chained notify in %s: mStack pings, then your own program runs (backup: %s.mstack-backup)" % (
            cfg_path, cfg_path))
    elif not ours:
        notes_out.append("%s already has a notify setting that could not be read; left it alone. To chain mStack, run: %s" % (
            cfg_path, line))
    if agents is not None:
        files.keep_backup(agents_path)
    files.write(agents_path, files.add_block(agents or "", block))
    notes_out.append("routing block in %s" % agents_path)
    return dict(base, written=True, message="\n".join(notes_out))


def remove(args, base, given_cfg, given_agents, text, agents):
    cfg_path, agents_path = base["config"], base["agents"]
    new_cfg, restored = remove_notify(text) if text else (None, None)
    new_agents = files.remove_block(agents) if agents else None
    would = []
    if new_cfg is not None:
        would.append("take mStack's notify line out of %s%s" % (
            files.shown(given_cfg), " and put your own back: %s" % restored if restored else ""))
    if new_agents is not None:
        would.append("take mStack's block out of %s" % files.shown(given_agents))
    if not would:
        return dict(base, written=False, changed=[], message="Nothing to remove: mStack's notify line and block are not in %s or %s." % (
            given_cfg, given_agents))
    if not args.write:
        return dict(base, written=False, would_change=would, message="Would %s.\nAsk the person; then run again with --write." % (
            "; ".join(would)))
    done = []
    if new_cfg is not None:
        done.append("notify line %s in %s" % (files.write_or_delete(cfg_path, new_cfg), cfg_path))
    if new_agents is not None:
        done.append("routing block %s in %s" % (files.write_or_delete(agents_path, new_agents), agents_path))
    return dict(base, written=True, changed=done, message="removed: " + "; ".join(done))
