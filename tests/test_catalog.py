#!/usr/bin/env python3
"""The skills catalog is the one source of truth: the tables in SKILL.md, AGENTS.md and docs/agents.md, the routing
block and the session start note all come from skills/mstack/catalog.json.

Everything runs in a throwaway folder and a throwaway mStack home.

  python3 tests/test_catalog.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def copy_of_repo(dest):
    """Just what the catalog touches: skills/mstack, AGENTS.md and docs/agents.md."""
    shutil.copytree(os.path.join(ROOT, "skills", "mstack"), os.path.join(dest, "skills", "mstack"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(dest, "docs"))
    shutil.copy(os.path.join(ROOT, "AGENTS.md"), dest)
    shutil.copy(os.path.join(ROOT, "docs", "agents.md"), os.path.join(dest, "docs"))
    return os.path.join(dest, "skills", "mstack", "scripts", "mstack.py")


def main():
    work = tempfile.mkdtemp(prefix="mstack-catalog-")
    env = dict(os.environ, MSTACK_HOME=os.path.join(work, "home"), HOME=work, CLAUDE_CONFIG_DIR=os.path.join(work, "c"),
               CODEX_HOME=os.path.join(work, "x"))

    def go(tool, *args):
        r = subprocess.run([sys.executable, tool] + list(args), capture_output=True, text=True, env=env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    try:
        tool = os.path.join(ROOT, "skills", "mstack", "scripts", "mstack.py")
        code, out, _ = go(tool, "catalog", "--check", "--json")
        data = json.loads(out)
        check(code == 0 and data["ok"] and data["differs"] == [], "catalog --check passes on the repository")
        check(len(data["files"]) == 3 and all(f["state"] == "same" for f in data["files"]),
              "catalog --check looked at SKILL.md, AGENTS.md and docs/agents.md")
        code, out, _ = go(tool, "catalog", "--json")
        check(code == 0 and json.loads(out)["ok"], "catalog with no flag is the same check")

        copy = os.path.join(work, "copy")
        ctool = copy_of_repo(copy)
        path = os.path.join(copy, "skills", "mstack", "catalog.json")
        cat = json.load(open(path))
        cat["skills"][1]["when"] += " An extra sentence."
        json.dump(cat, open(path, "w"), indent=2)
        code, out, _ = go(ctool, "catalog", "--check", "--json")
        data = json.loads(out)
        check(code == 1 and not data["ok"] and sorted(data["differs"]) == ["AGENTS.md", "docs/agents.md", "skills/mstack/SKILL.md"]
              and "error" in data, "changing one when line makes --check fail for exactly the three generated files")
        code, out, _ = go(ctool, "catalog", "--check")
        check(code == 1 and "AGENTS.md" in out and "docs/agents.md" in out, "the plain --check names each file")
        before = open(os.path.join(copy, "AGENTS.md")).read()
        hand = before.replace("# mStack, for agents", "# mStack, for agents (edited by hand)")
        open(os.path.join(copy, "AGENTS.md"), "w").write(hand)
        code, out, _ = go(ctool, "catalog", "--write", "--json")
        data = json.loads(out)
        check(code == 0 and data["ok"] and len(data["written"]) == 3, "--write rewrites the three generated parts")
        after = open(os.path.join(copy, "AGENTS.md")).read()
        check("An extra sentence." in after and "(edited by hand)" in after,
              "--write changes the generated part and leaves the hand written text alone")
        code, out, _ = go(ctool, "catalog", "--check", "--json")
        check(code == 0 and json.loads(out)["ok"], "after --write, --check passes again")
        code, out, _ = go(ctool, "catalog", "--write", "--json")
        check(code == 0 and json.loads(out)["written"] == [], "--write twice changes nothing the second time")
        text = open(os.path.join(copy, "docs", "agents.md")).read().replace("<!-- mstack:catalog:start -->", "")
        open(os.path.join(copy, "docs", "agents.md"), "w").write(text)
        code, out, _ = go(ctool, "catalog", "--write", "--json")
        data = json.loads(out)
        check(code == 1 and not data["ok"] and "markers" in data["error"], "--write names a file that has no markers, as JSON")

        # the routing block and the session start note use the catalog's when line and offer the index commands
        entries = json.load(open(os.path.join(ROOT, "skills", "mstack", "catalog.json")))["skills"]
        for name, args in (("routing", ["routing", "--json"]), ("session start", ["session-start", "--json"])):
            code, out, _ = go(tool, *args)
            text = json.loads(out)["text"]
            check(code == 0 and all(e["when"] in text for e in entries),
                  "the %s carries every skill's when line from the catalog" % name)
            mstack = [e for e in entries if e["name"] == "mstack"][0]
            check(all(c["command"] in text and c["use_when"] in text for c in mstack["commands"])
                  and "status" in text and "brief" in text and "rules" in text,
                  "the %s names status, brief, rules and the other mstack commands" % name)
        code, out, _ = go(tool, "disable", "crew", "--json")
        code, out, _ = go(tool, "routing", "--json")
        text = json.loads(out)["text"]
        check("- crew:" not in text and "Switched off by the person (do not use): crew" in text,
              "a switched off skill leaves the routing block's list")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
