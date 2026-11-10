#!/usr/bin/env python3
"""Checks every skill is packaged the same way: frontmatter, the shared "before you start" rules, a
description short enough for every agent, and a mention in the index, README, AGENTS.md and docs/agents.md.
Also checks the Claude Code plugin files.

  python3 tests/test_skills.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as fh:
        return fh.read()


def main():
    names = sorted(d for d in os.listdir(os.path.join(ROOT, "skills")) if os.path.exists(os.path.join(ROOT, "skills", d, "SKILL.md")))
    catalog = [e["name"] for e in json.loads(read("skills", "mstack", "catalog.json"))["skills"]]
    check(sorted(catalog) == names and len(set(catalog)) == len(catalog),
          "every skill folder has one catalog entry and every entry has a folder (%s)" % ", ".join(names))
    check(all(e.get("when") for e in json.loads(read("skills", "mstack", "catalog.json"))["skills"]), "every catalog entry says when it switches on")
    index, readme, agents, page = read("skills", "mstack", "SKILL.md"), read("README.md"), read("AGENTS.md"), read("docs", "agents.md")
    for n in names:
        text = read("skills", n, "SKILL.md")
        m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
        check(bool(m) and m.group(1) == n, "%s: frontmatter name matches its folder" % n)
        check(bool(m) and 100 <= len(m.group(2)) <= 1024, "%s: description fits every agent (%d characters)" % (
            n, len(m.group(2)) if m else 0))
        if n != "mstack":
            check("## Before you start (every mStack skill)" in text and "~/.mstack/config.json" in text
                  and "~/.mstack/learned/%s.md" % n in text and "mstack.py log %s" % n in text,
                  "%s: has the off switch, learned rules and journal" % n)
            check("| %s |" % n in index, "%s: listed in the mstack index" % n)
        for doc, label in ((readme, "README"), (agents, "AGENTS.md"), (page, "docs/agents.md")):
            check(n in doc, "%s: mentioned in %s" % (n, label))
    plugin = json.loads(read(".claude-plugin", "plugin.json"))
    market = json.loads(read(".claude-plugin", "marketplace.json"))
    check(plugin["name"] == "mstack" and plugin["license"] == "MIT", "plugin.json names mstack, MIT")
    check(market["plugins"][0]["source"] == "./" and market["plugins"][0]["version"] == plugin["version"],
          "marketplace.json points at this repository, same version")
    hooks = json.loads(read("hooks", "hooks.json"))
    cmd = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    path = cmd.split('"')[1].replace("${CLAUDE_PLUGIN_ROOT}", ROOT)
    check(os.path.exists(path) and cmd.endswith("session-start"), "the plugin's session start hook runs mstack.py session-start")
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
