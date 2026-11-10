"""The shared basics for mstack.py and the modules beside it: the home folder, the config file, the list of
skills, the skill-name check and the JSON-aware error.

Python 3.9 or later, standard library only. Nothing here imports mstack.py, so every module can use it.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))          # the folder holding every mStack skill
DEFAULTS = {"disabled": [], "review_every": 10, "notify_reply_text": False,
            "ping": {"desktop": True, "ntfy_topic": "", "ntfy_server": "https://ntfy.sh"}}


class Fail(Exception):
    """A plain error: the message, the exit code, and any extra fields for the JSON form."""

    def __init__(self, message, code=1, **extra):
        super().__init__(message)
        self.message, self.code, self.extra = message, code, extra


def report_failure(e, as_json):
    """Print a Fail the way the caller asked (JSON on standard output, or a plain line on standard error), then exit."""
    if as_json:
        print(json.dumps(dict({"ok": False, "error": e.message}, **e.extra), indent=2))
    else:
        print(e.message, file=sys.stderr)
    raise SystemExit(e.code)


class JsonArgParser(argparse.ArgumentParser):
    """An argument parser whose usage errors are JSON when --json was on the command line."""
    json_mode = False

    def error(self, message):
        if JsonArgParser.json_mode:
            print(json.dumps({"ok": False, "error": message}, indent=2))
            raise SystemExit(2)
        super().error(message)


def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, *parts)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    path = home("config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                mine = json.load(fh)
        except ValueError:
            mine = {}
        if not isinstance(mine, dict):
            mine = {}
        for k, v in mine.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg):
    os.makedirs(home(), exist_ok=True)
    with open(home("config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def summarise(description):
    """The description's first sentence (or two, if the first is short), at most about 200 characters."""
    parts = re.split(r"(?<=\.)\s+", description.strip())
    text = parts[0]
    if len(text) < 40 and len(parts) > 1:
        text += " " + parts[1]
    if len(text) > 200:
        text = text[:197].rsplit(" ", 1)[0] + "..."
    return text


def skills():
    out = []
    for name in sorted(os.listdir(SKILLS)):
        path = os.path.join(SKILLS, name, "SKILL.md")
        if os.path.exists(path):
            fm = frontmatter(path)
            out.append({"name": fm.get("name", name), "folder": os.path.join(SKILLS, name),
                        "description": fm.get("description", ""), "summary": summarise(fm.get("description", ""))})
    return out


def is_on(name, cfg=None):
    return name not in (cfg or load_config()).get("disabled", [])


def check_skill(name):
    """Return name when it is one of the skills `mstack.py skills` lists; otherwise stop with exit 2 and the valid names."""
    names = [s["name"] for s in skills()]
    if name not in names:
        raise Fail("No mStack skill called %r. The skills are: %s" % (name, ", ".join(names)), 2, valid=names)
    return name


def say(args, data, text):
    print(json.dumps(data, indent=2) if getattr(args, "json", False) else text)
