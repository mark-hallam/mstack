#!/usr/bin/env python3
"""The safety scan (tests/leak_scan.py) and the style check (tests/style_scan.py) are two tools: every pattern
lives in exactly one of them, each prints its own result line, and each can be pointed at another folder with
MSTACK_SCAN_ROOT.

  python3 tests/test_scans.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
failures = []

SAFETY = ["a home folder path", "a private user name", "a private project name", "an email address", "a GitHub token",
          "an API key", "a private key"]
STYLE = ["an em or en dash", "a hype word"]


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def run(script, root=None):
    env = dict(os.environ)
    if root:
        env["MSTACK_SCAN_ROOT"] = root
    r = subprocess.run([sys.executable, os.path.join(HERE, script)], capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, r.stdout


def names(script):
    with open(os.path.join(HERE, script), encoding="utf-8") as fh:
        return re.findall(r'^    \("([^"]+)", re\.compile', fh.read(), re.M)


def planted(text):
    d = tempfile.mkdtemp(prefix="mstack-scan-test-")
    with open(os.path.join(d, "note.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return d


def main():
    check(names("leak_scan.py") == SAFETY, "leak_scan.py holds only the safety patterns")
    check(names("style_scan.py") == STYLE, "style_scan.py holds only the style patterns")
    check(sorted(names("leak_scan.py") + names("style_scan.py")) == sorted(SAFETY + STYLE),
          "every pattern is in exactly one of the two files")

    code, out = run("leak_scan.py")
    check(code == 0 and "leak scan: clean" in out, "the repository passes the leak scan")
    code, out = run("style_scan.py")
    check(code == 0 and "style scan: clean" in out, "the repository passes the style scan")

    dash = "A sentence \u2014 with a dash."
    hype = "This will " + "revolutio" + "nise everything."
    leak = "See /ho" + "me/someone/file and write to person" + "@example.com."
    for text, leak_hit, style_hit in ((dash, False, True), (hype, False, True), (leak, True, False), ("Plain text, fine.", False, False)):
        d = planted(text)
        code, out = run("leak_scan.py", d)
        check((code != 0) == leak_hit and ("leak scan: clean" in out) == (not leak_hit), "leak scan on %r: %s" % (text[:24], "problems" if leak_hit else "clean"))
        code, out = run("style_scan.py", d)
        check((code != 0) == style_hit and ("style scan: clean" in out) == (not style_hit), "style scan on %r: %s" % (text[:24], "problems" if style_hit else "clean"))

    for target in ("run_all.py", os.path.join("..", ".github", "workflows", "test.yml")):
        with open(os.path.join(HERE, target), encoding="utf-8") as fh:
            body = fh.read()
        check("leak_scan.py" in body and "style_scan.py" in body, "%s runs both scans" % os.path.basename(target))

    print("\n%s" % ("both scans behave" if not failures else "FAILED: %d" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
