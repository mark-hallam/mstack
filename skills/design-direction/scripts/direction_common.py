"""Shared pieces for the design-direction tool: the project folder, its config, rounds and plain output."""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SKILLS = os.path.dirname(SKILL)
EVAL_SCRIPTS = os.path.join(SKILLS, "multi-evaluator", "scripts")     # the sibling skill's journey driver and helpers
if os.path.isdir(EVAL_SCRIPTS) and EVAL_SCRIPTS not in sys.path:
    sys.path.insert(0, EVAL_SCRIPTS)
CONFIG_NAME = "direction.json"
PLACEHOLDER = re.compile(r"\[\[.*?\]\]", re.S)
SCHEMES = ("light", "dark")


def fail(message):
    raise SystemExit(message)


class JsonParser(argparse.ArgumentParser):
    """An argparse parser whose usage errors become {"ok": false, "error": ...} when --json was given."""
    json_mode = False

    def error(self, message):
        if JsonParser.json_mode:
            raise SystemExit("%s: %s" % (self.prog, message))
        super().error(message)


def run_cli(ap, argv=None):
    """Parse and run. With --json, every error (a message, a usage mistake or a crash) is one JSON object
    {"ok": false, "error": ...} on standard output and the exit code is 1."""
    argv = sys.argv[1:] if argv is None else list(argv)
    JsonParser.json_mode = "--json" in argv
    try:
        args = ap.parse_args(argv)
        args.fn(args)
    except SystemExit as e:
        if JsonParser.json_mode and isinstance(e.code, str):
            print(json.dumps({"ok": False, "error": e.code}))
            sys.exit(1)
        raise
    except Exception as e:
        if not JsonParser.json_mode:
            raise
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}))
        sys.exit(1)


def say(args, data, text):
    print(json.dumps(data, indent=2) if getattr(args, "json", False) else text, flush=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def design_paragraph(path):
    """The first HTML comment of an option file, as one line of text ('' if it has none)."""
    m = re.search(r"<!--(.*?)-->", read(path)[:6000], re.S) if os.path.exists(path) else None
    return " ".join(m.group(1).split()) if m else ""


class Project(object):
    def __init__(self, folder):
        self.dir = os.path.abspath(folder or ".")
        self.path = os.path.join(self.dir, CONFIG_NAME)
        if not os.path.exists(self.path):
            fail("No %s in %s. Run init first." % (CONFIG_NAME, self.dir))
        try:
            self.cfg = json.loads(read(self.path))
        except ValueError as e:
            fail("%s is not valid JSON: %s" % (self.path, e))

    @property
    def name(self):
        return self.cfg.get("name", "Product")

    def save(self):
        write(self.path, json.dumps(self.cfg, indent=2) + "\n")

    def brief_path(self):
        return os.path.join(self.dir, self.cfg.get("brief", "BRIEF.md"))

    def brief_text(self):
        if not os.path.exists(self.brief_path()):
            fail("The brief %s is missing. Run init, or write it." % self.brief_path())
        return read(self.brief_path())

    def brief_open_items(self):
        return PLACEHOLDER.findall(self.brief_text())

    def rdir(self, k, *parts):
        return os.path.join(self.dir, "rounds", "r%d" % k, *parts)

    def rounds(self):
        return self.cfg.setdefault("rounds", [])

    def round(self, k):
        return next((r for r in self.rounds() if r["n"] == k), None)

    def latest(self, mode=None):
        rs = [r for r in self.rounds() if mode in (None, r["mode"])]
        return rs[-1] if rs else None

    def need_round(self, k=None):
        r = self.round(k) if k else self.latest()
        if not r:
            fail("No round yet. Run options first." if not k else "There is no round %s." % k)
        return r

    def item_file(self, k, item):
        return self.rdir(k, "options", item + ".html")

    def built(self, r):
        return [i for i in r["ids"] if os.path.exists(self.item_file(r["n"], i))]

    def builders(self):
        found = [b for b in self.cfg.get("builders", []) if b.get("enabled", True)]
        return found or [{"id": "agent", "name": "The agent running this skill", "kind": "agent"}]

    def viewports(self):
        return self.cfg.get("viewports") or {"desktop": {"w": 1440, "h": 1000}, "phone": {"w": 390, "h": 844, "mobile": True}}

    def shot_names(self, item):
        return ["%s-%s-%s" % (item, v, s) for v in self.viewports() for s in SCHEMES]


def label(item):
    """option-a -> Option A, variant-2 -> Variant 2."""
    kind, _, tag = item.partition("-")
    return "%s %s" % (kind.capitalize(), tag.upper())
