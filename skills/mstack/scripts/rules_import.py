"""rules import --from: propose rules from any Markdown or text files (or folders of them), from any agent.

Python 3.9 or later, standard library only. Nothing here writes a rule: it only returns proposals, which
`rules accept` writes after the person chooses.
"""
import os
import re

SUFFIXES = (".md", ".markdown", ".txt")
MAX_FILES, MAX_BYTES = 200, 1000000
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def files_in(sources):
    """The readable files named by --from: a file itself, or the Markdown and text files inside a folder."""
    out = []
    for src in sources:
        if os.path.isdir(src):
            for base, dirs, names in os.walk(src):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for n in sorted(names):
                    if n.lower().endswith(SUFFIXES) and not n.startswith("."):
                        out.append((os.path.join(base, n), os.path.relpath(os.path.join(base, n), src)))
        else:
            out.append((src, os.path.basename(src)))
    return out[:MAX_FILES]


def rules_in(text, rules):
    """[(heading, rule)] from one file: its bullet lines, each under the file's own heading when that is one of the
    six, otherwise under the best guess; a file with no bullets gives its first line."""
    meta, body = rules.split_memory(text)
    known = dict((h.lower(), h) for h in rules.HEADINGS)
    if meta.get("type") in ("feedback", "project"):
        rule = rules.first_rule(body)
        return [(rules.guess_heading(meta.get("name", ""), meta.get("description", ""), body), rule)] if rule else []
    found, section = [], None
    for line in body.splitlines():
        h = HEADING.match(line)
        if h:
            section = known.get(h.group(1).strip().lower())
            continue
        b = BULLET.match(line)
        if b:
            rule = re.sub(r"\s+", " ", b.group(1).replace("**", "")).strip()[:200]
            if len(rule) >= 8 and rule.lower().rstrip(".") != "none" and not rule.lower().startswith("http"):
                found.append((section or rules.guess_heading(rule), rule))
    if not found:
        rule = rules.first_rule(body)
        if rule and len(rule) >= 8:
            found.append((rules.guess_heading(rule), rule))
    return found


def proposals_from_files(sources, rules, start=0):
    """Proposals numbered from start + 1, the same shape as the memory ones. Raises ValueError for a missing path."""
    for src in sources:
        if not os.path.exists(src):
            raise ValueError("The file or folder to read does not exist: %s" % src)
    out, seen = [], set()
    for path, label in files_in(sources):
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for heading, rule in rules_in(text, rules):
            key = " ".join(rule.lower().split())
            if key not in seen:
                seen.add(key)
                out.append({"n": start + len(out) + 1, "heading": heading, "rule": rule, "from": label})
    return out
