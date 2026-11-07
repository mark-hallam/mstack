#!/usr/bin/env python3
"""The journey driver's select step: an option is found by its value or its visible text, the page's change
listener fires, and a value that matches nothing is reported NOT FOUND instead of silently clearing the choice."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVE = os.path.join(ROOT, "skills", "multi-evaluator", "scripts", "drive.mjs")
sys.path.insert(0, os.path.join(ROOT, "skills", "multi-evaluator", "scripts"))
import eval_loop  # noqa: E402

PAGE = """<!doctype html><html><body><h1>Pick a plan</h1>
<select id="plan"><option value="">Choose a plan</option><option value="w">Weekly plan</option>
<option value="m">Monthly plan</option></select><p id="out">nothing yet</p>
<script>document.getElementById('plan').addEventListener('change', e => {
  document.getElementById('out').textContent = 'changed to ' + e.target.value; });</script></body></html>"""

failed = []


def check(ok, what):
    print(("pass  " if ok else "FAIL  ") + what)
    if not ok:
        failed.append(what)


def drive(work, url, steps):
    out = tempfile.mkdtemp(prefix="drive-out-", dir=work)
    spec = os.path.join(work, "steps-%d.json" % len(os.listdir(work)))
    with open(spec, "w", encoding="utf-8") as fh:
        json.dump({"viewport": {"w": 800, "h": 600}, "steps": [{"do": "goto", "url": url}] + steps}, fh)
    subprocess.run(["node", DRIVE, spec, out], capture_output=True, text=True, timeout=120)
    with open(os.path.join(out, "log.txt"), encoding="utf-8") as fh:
        return fh.read()


def main():
    if not shutil.which("node"):
        print("skip  node is not installed, so the driver cannot run")
        return
    work = tempfile.mkdtemp(prefix="mstack-select-", dir=eval_loop.tmp_base())
    try:
        page = os.path.join(work, "page.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(PAGE)
        url = "file://" + page
        log = drive(work, url, [{"do": "select", "sel": "#plan", "value": "m"},
                                {"do": "eval", "js": "document.getElementById('out').textContent"}])
        check("selected \"Monthly plan\"" in log, "an option is found by its value")
        check("changed to m" in log, "the page's change listener fired")
        log = drive(work, url, [{"do": "select", "sel": "#plan", "value": "weekly plan"},
                                {"do": "eval", "js": "document.getElementById('out').textContent"}])
        check("selected \"Weekly plan\"" in log, "an option is found by its visible text, whatever the case")
        check("changed to w" in log, "the change listener fired for the text match too")
        log = drive(work, url, [{"do": "select", "sel": "#plan", "value": "Yearly plan"},
                                {"do": "eval", "js": "document.getElementById('plan').value"}])
        check("NOT FOUND: no option matches \"Yearly plan\"" in log and "\"Weekly plan\"" in log,
              "a value that matches nothing says NOT FOUND and lists the options")
        check('result: ""' in log, "and the choice is left as it was, not cleared to something else")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failed:
        print("\nfailed: %d" % len(failed))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
