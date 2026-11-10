"""The skills catalog: one file (skills/mstack/catalog.json) says which skills exist and when each switches on.

Python 3.9 or later, standard library only. The tables in skills/mstack/SKILL.md, AGENTS.md and docs/agents.md are
generated from it between marker comments, and the routing block and the session start note read the same
lines. `mstack.py catalog --check` lists every file whose generated part differs; `--write` rewrites them.
"""
import json
import os
import re

from mbase import SKILLS, Fail, say

START, END = "<!-- mstack:catalog:start -->", "<!-- mstack:catalog:end -->"
ROOT = os.path.dirname(SKILLS)                       # the folder holding skills/, AGENTS.md and docs/
FILE = os.path.join(SKILLS, "mstack", "catalog.json")
TARGETS = (("skills/mstack/SKILL.md", "skill"), ("AGENTS.md", "agents"), ("docs/agents.md", "page"))
REGION = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def load():
    try:
        with open(FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data["skills"]
        assert isinstance(entries, list) and all(isinstance(e, dict) and e.get("name") and e.get("when") for e in entries)
    except (OSError, ValueError, KeyError, AssertionError):
        raise Fail("Could not read the skills catalog %s (it must hold a \"skills\" list, each with a name and a "
                   "\"when\" line)." % FILE)
    return entries


def entry(name, entries=None):
    for e in entries or load():
        if e["name"] == name:
            return e
    return None


def cell(text):
    return text.replace("|", "\\|")


def command_lines(e, prefix):
    return ["- `%s %s`: %s" % (prefix, c["command"], c["use_when"]) for c in e.get("commands", [])]


def region(kind, entries=None):
    """The generated text for one kind of file, markers included."""
    entries = entries or load()
    head, rule = {"skill": ("| Skill | Switches on when | Default |", "|---|---|---|"),
                  "agents": ("| Skill | Switches on when | Start here |", "|---|---|---|"),
                  "page": ("| Skill | Switches on when |", "|---|---|")}[kind]
    rows = []
    for e in entries:
        row = [e["name"], cell(e["when"])]
        if kind == "skill":
            row.append(e.get("default", "On"))
        elif kind == "agents":
            row.append("`skills/%s/SKILL.md`" % e["name"])
        rows.append("| " + " | ".join(row) + " |")
    out = [START, head, rule] + rows
    prefix = "MSTACK" if kind == "skill" else "mstack.py"
    for e in entries:
        if e.get("commands"):
            out += ["", "What %s offers (`%s <command>`):" % (e["name"], prefix), ""] + command_lines(e, prefix)
    out.append(END)
    return "\n".join(out)


def wanted():
    """(relative path, absolute path, the text the file should hold in its generated part)."""
    entries = load()
    return [(rel, os.path.join(ROOT, *rel.split("/")), region(kind, entries)) for rel, kind in TARGETS]


def current(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None, None
    m = REGION.search(text)
    return text, (m.group(0) if m else None)


def audit():
    """One row per generated file: path, state ('same', 'differs', 'no markers', 'missing')."""
    rows = []
    for rel, path, want in wanted():
        text, have = current(path)
        state = "missing" if text is None else "no markers" if have is None else "same" if have == want else "differs"
        rows.append({"file": rel, "path": path, "state": state, "want": want})
    return rows


def cmd_catalog(args):
    rows = audit()
    bad = [r for r in rows if r["state"] != "same" and r["state"] != "missing"]
    if args.write:
        for r in bad:
            if r["state"] == "no markers":
                raise Fail("%s has no %s ... %s markers to write between." % (r["file"], START, END), 1, file=r["file"])
        for r in bad:
            text, _ = current(r["path"])
            with open(r["path"], "w", encoding="utf-8") as fh:
                fh.write(REGION.sub(lambda m: r["want"], text, 1))
        say(args, {"ok": True, "written": [r["file"] for r in bad], "files": [r["file"] for r in rows]},
            "rewrote: %s" % ", ".join(r["file"] for r in bad) if bad else "every generated part already matches the catalog")
        return
    names = [r["file"] for r in bad]
    data = {"ok": not bad, "differs": names, "files": [{"file": r["file"], "state": r["state"]} for r in rows],
            "catalog": os.path.relpath(FILE, ROOT)}
    if bad:
        data["error"] = "The generated part differs from the catalog in: %s. Run: mstack.py catalog --write" % ", ".join(names)
    say(args, data, "every generated part matches the catalog" if not bad else data["error"])
    if bad:
        raise SystemExit(1)
