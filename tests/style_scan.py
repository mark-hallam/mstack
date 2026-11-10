#!/usr/bin/env python3
"""House writing style check for every file in this repository. Run before every commit.

Fails on: dashes used as punctuation, and hype words. The safety checks (paths, emails, tokens, private
names) are a separate tool, tests/leak_scan.py. Embedded images inside HTML reports are skipped.
MSTACK_SCAN_ROOT checks another folder.

  python3 tests/style_scan.py
"""
import os
import re
import sys

ROOT = os.environ.get("MSTACK_SCAN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT = {".md", ".py", ".mjs", ".js", ".json", ".html", ".txt", ".yml", ".yaml", ".toml", ".sh", ""}

# Written in pieces so this file does not match itself.
CHECKS = [
    ("an em or en dash", re.compile("[\\u2014\\u2013]")),
    # "trans" + "form" as a verb; the CSS property text-transform is fine.
    ("a hype word", re.compile(r"\b(revolutio" + r"ni[sz]e\w*|(?<!text-)trans" + r"form(s|ed|ing)?\b|game.chan" + r"ger|"
                               r"next.gener" + r"ation|ai.pow" + r"ered)", re.I)),
]
ALLOWED = set()   # (file, matched text) pairs that are fine, if a real exception ever comes up


def files():
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            path = os.path.join(base, n)
            if n in SKIP_DIRS:            # in a git worktree, .git is a file pointing at the main checkout
                continue
            if os.path.splitext(n)[1].lower() in TEXT:
                yield path


def main():
    problems = []
    for path in files():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        text = re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "data:image", text)   # embedded pictures
        for i, line in enumerate(text.splitlines(), 1):
            for what, rx in CHECKS:
                m = rx.search(line)
                if m and (rel, m.group(0)) not in ALLOWED:
                    problems.append("%s:%d: %s (%r)" % (rel, i, what, m.group(0)[:40]))
    for p in problems:
        print(p)
    print("style scan: %s" % ("clean" if not problems else "%d problems" % len(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
