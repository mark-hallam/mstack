#!/usr/bin/env python3
"""A stand-in design builder for the design-direction test: no AI and no network.

It reads the brief on standard input the way a real builder would, keeps a copy of what it was given, and
writes a tiny valid option page that starts with a design-language comment and has colour tokens on :root.

  python3 stand_in_builder.py --out <file> --letter <a or 1> --work <folder>   (brief on standard input)
"""
import argparse
import os
import sys

PAGE = """<!-- Design language: a stand-in for item %(letter)s. Reference points: none, this is a test. Trade-off: it says nothing true about design. -->
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stand-in %(letter)s</title>
<style>
:root { --bg: #ffffff; --text: #1d1d1f; --muted: #6e6e73; --faint: #bbbbbb; --accent: #0066cc; --accent-ink: #ffffff;
  --radius: 12px; --shadow: 0 1px 3px rgba(0,0,0,.2); --space: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #1c1c1e; --text: #f5f5f7; --muted: #a1a1a6; --faint: #3a3a3c; --accent: #0a84ff; --accent-ink: #000000; } }
:root[data-theme="dark"] { --bg: #1c1c1e; --text: #f5f5f7; --muted: #a1a1a6; --faint: #3a3a3c; --accent: #0a84ff; --accent-ink: #000000; }
body { margin: 0; padding: var(--space); background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.card { border-radius: var(--radius); box-shadow: var(--shadow); padding: var(--space); }
p { color: var(--muted); }
a.button { background: var(--accent); color: var(--accent-ink); border-radius: var(--radius); padding: 8px 14px; text-decoration: none; }
</style></head>
<body><main class="card"><h1>Stand-in %(letter)s</h1><p>The same example scenario, in every option.</p><a class="button" href="#go">Go</a></main></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--letter", required=True)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    brief = sys.stdin.read()
    os.makedirs(args.work, exist_ok=True)
    with open(os.path.join(args.work, "brief-seen.md"), "w", encoding="utf-8") as fh:
        fh.write(brief)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(PAGE % {"letter": args.letter.upper()})


if __name__ == "__main__":
    main()
