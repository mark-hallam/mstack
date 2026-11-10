#!/usr/bin/env python3
"""Safety scan for every file in this repository. Run before every commit.

Fails on: home folder paths, email addresses, things that look like secret tokens, private keys, and private
workspace names. The house writing style (dashes, hype words) is checked apart, by tests/style_scan.py.
Embedded images inside HTML reports are skipped. MSTACK_SCAN_ROOT scans another folder.

  python3 tests/leak_scan.py
"""
import os
import re
import sys

ROOT = os.environ.get("MSTACK_SCAN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT = {".md", ".py", ".mjs", ".js", ".json", ".html", ".txt", ".yml", ".yaml", ".toml", ".sh", ""}

# Written in pieces so this file does not match itself.
CHECKS = [
    ("a home folder path", re.compile(r"/(Users|home)/[A-Za-z0-9_.-]+/")),
    ("a private user name", re.compile("Mark" + "Mark", re.I)),
    ("a private project name", re.compile(r"\blvl" + r"me\b", re.I)),
    ("an email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("a GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("an API key", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,})")),
    ("a private key", re.compile("-----BEGIN [A-Z ]*PRIV" + "ATE KEY-----")),
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
    print("leak scan: %s" % ("clean" if not problems else "%d problems" % len(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
