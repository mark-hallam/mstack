#!/usr/bin/env python3
"""The measured audit: the driver's audit step measures a known page, and capture and the report carry it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MSTACK_HOME"] = __import__("tempfile").mkdtemp(prefix="mstack-home-")   # the evaluator scoreboard writes here, never to the real home
SCRIPTS = os.path.join(ROOT, "skills", "multi-evaluator", "scripts")
DRIVE = os.path.join(SCRIPTS, "drive.mjs")
LOOP = os.path.join(SCRIPTS, "eval_loop.py")
STATIC = os.path.join(ROOT, "tests", "static_server.py")
sys.path.insert(0, SCRIPTS)
import eval_loop  # noqa: E402
from eval_common import free_port  # noqa: E402

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Audit page</title>
<style>
body { margin: 0; font: 16px sans-serif; color: #000; background: #fff; }
p.grey { color: #86868b; font-size: 13px; }
.wide { position: absolute; top: 0; left: 0; width: 600px; height: 4px; background: #08f; }
.spin { width: 20px; height: 20px; background: #c00; animation: spin 1s linear infinite; }
@keyframes spin { to { opacity: 0.5; } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.tall { height: 1500px; }
</style></head><body>
<h1>Black heading</h1>
<h3>Skipped level</h3>
<p class="grey">Quiet grey note that is hard to read.</p>
<p>Please save your work often. Please save your work often. Please save your work often.</p>
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="a dot">
<div class="wide"></div><div class="spin"></div><div class="tall"></div>
</body></html>"""

failed = []


def check(ok, what):
    print(("pass  " if ok else "FAIL  ") + what, flush=True)
    if not ok:
        failed.append(what)


def serve(folder):
    port = free_port()
    proc = subprocess.Popen([sys.executable, STATIC, str(port), folder], stdout=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    return proc, port


def audit_at(work, url, w, h, mobile):
    out = os.path.join(work, "out-%d" % w)
    spec = os.path.join(work, "steps-%d.json" % w)
    with open(spec, "w", encoding="utf-8") as fh:
        json.dump({"viewport": {"w": w, "h": h, "mobile": mobile},
                   "steps": [{"do": "goto", "url": url, "ms": 600}, {"do": "audit"}]}, fh)
    subprocess.run(["node", DRIVE, spec, out], capture_output=True, text=True, timeout=120)
    path = os.path.join(out, "audit.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    if not shutil.which("node") or not eval_loop.find_chrome():
        print("skipped: no Chrome")
        return
    work = tempfile.mkdtemp(prefix="mstack-audit-", dir=eval_loop.tmp_base())
    site = os.path.join(work, "site")
    os.makedirs(site)
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(PAGE)
    proc, port = serve(site)
    try:
        url = "http://127.0.0.1:%d/" % port
        phone = audit_at(work, url, 390, 844, True)
        desk = audit_at(work, url, 1440, 1000, False)
        check(phone is not None and desk is not None, "the audit step writes audit.json")
        if phone and desk:
            grey = [c for c in phone["contrast"] if "Quiet grey" in c["text"]]
            check(len(grey) == 1 and 3.5 <= grey[0]["ratio"] <= 3.7, "the grey paragraph fails contrast at about 3.6")
            check(grey and grey[0]["fg"] == "#86868b" and grey[0]["bg"] == "#ffffff", "colours are reported as hex")
            check(not any("Black heading" in c["text"] for c in phone["contrast"]), "the black heading passes")
            check(any("please save your work often" in r["phrase"].lower() and r["count"] == 3 for r in phone["repeats"]),
                  "the repeated phrase is found three times")
            check(phone["images_without_alt"]["count"] == 1, "one image has no alt text")
            check(phone["sideways_scroll"] is True and desk["sideways_scroll"] is False,
                  "sideways scroll at 390 wide, none at 1440")
            check(phone["motion"] == {"always": 1, "reduced": 0}, "reduce motion is respected: %s" % phone["motion"])
            check(phone["heading_skips"] == 1 and phone["headings"] == "h1 h3", "one heading skip")
            check(phone["screens"] > 1, "the phone page is more than one screen long")
            check(phone["words"] > 10 and phone["weight_kb"] > 0, "words and page weight are measured")

        review = os.path.join(work, "review")
        os.makedirs(review)
        subprocess.run([sys.executable, LOOP, "init", "--name", "Audit test", "--dir", review], capture_output=True, text=True, check=True)
        cfg = {"name": "Audit test", "about": "A page with known problems.",
               "target": {"url": "http://127.0.0.1:{port}/", "start": [sys.executable, STATIC, "{port}", site], "cwd": site},
               "views": [{"id": "home", "name": "Home", "group": "Phone", "viewport": "phone",
                          "steps": [{"do": "goto", "url": "{url}", "ms": 600}]}],
               "journeys": [{"id": 1, "name": "Look", "task": "Open the page."}],
               "criteria": [{"name": "Clear", "means": "obvious."}],
               "reviewers": [{"id": "a", "name": "Reviewer A", "kind": "agent"}]}
        with open(os.path.join(review, "mstack-eval.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)

        def loop(*a):
            return subprocess.run([sys.executable, LOOP] + list(a) + ["--dir", review], capture_output=True, text=True, timeout=300)
        check(loop("start-round").returncode == 0, "start-round")
        cap = loop("capture", "--json")
        check(cap.returncode == 0, "capture succeeds")
        shot = os.path.join(review, "rounds", "r1", "shots", "home.audit.json")
        check(os.path.exists(shot), "capture saves home.audit.json beside the screenshot")
        try:
            views = json.loads(cap.stdout)["views"]
            check(views[0]["audit"] and views[0]["audit"]["images_without_alt"]["count"] == 1, "--json carries the audit")
        except Exception as e:
            check(False, "--json carries the audit (%s)" % e)
        rep = loop("report")
        path = os.path.join(review, "report.html")
        html = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        check("Measured" in html and "#86868b" in html, "the report has a Measured section with the failing colour")
    finally:
        proc.terminate()
        shutil.rmtree(work, ignore_errors=True)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
