#!/usr/bin/env python3
"""Self-test for away-mode: the layered away detection (the person's words, the agent's hints, the machine),
expiry, the set and back records, the session start rule, and a real render to PDF and PNG when Google
Chrome or Chromium is present (skipped cleanly when it is not).

Everything runs in a throwaway folder: MSTACK_HOME points there, and MSTACK_AWAY_MACHINE stands in for the
computer's own idle, lock and display signals, so the test never depends on who is at this keyboard.

  python3 tests/test_away.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "skills", "away-mode", "scripts", "away.py")
MSTACK = os.path.join(ROOT, "skills", "mstack", "scripts", "mstack.py")
sys.path.insert(0, os.path.join(ROOT, "skills", "away-mode", "scripts"))
import away_render  # noqa: E402

failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def main():
    work = tempfile.mkdtemp(prefix="mstack-away-test-")
    home = os.path.join(work, "home")
    env = dict(os.environ, MSTACK_HOME=home)
    env.pop("MSTACK_AWAY_MACHINE", None)

    def run(*args, machine=None, expect=0, tool=TOOL):
        e = dict(env)
        if machine is not None:
            e["MSTACK_AWAY_MACHINE"] = json.dumps(machine)
        r = subprocess.run([sys.executable, tool] + list(args), capture_output=True, text=True, env=e, timeout=180)
        if r.returncode != expect:
            print(r.stdout, r.stderr)
            raise SystemExit("FAIL  %s %s exited %d, expected %d" % (os.path.basename(tool), " ".join(args), r.returncode, expect))
        return r.stdout

    def status(*hints, machine=None):
        args = ["status"]
        for h in hints:
            args += ["--hint", h]
        return json.loads(run(*args, machine=machine))

    def words_file(**rec):
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "away.json"), "w") as fh:
            json.dump(rec, fh)

    active = {"idle_seconds": 30, "locked": False, "display_asleep": False}
    idle = {"idle_seconds": 15 * 60, "locked": False, "display_asleep": False}
    try:
        # the machine
        s = status(machine=active)
        check(s["away"] is False and s["deliver"] == "local" and "ago" in s["why"], "recent keyboard or mouse means present")
        s = status(machine=idle)
        check(s["away"] is True and s["deliver"] == "phone" and "15 minutes" in s["why"], "idle past 10 minutes means away")
        s = status(machine={"idle_seconds": 60, "locked": True, "display_asleep": False})
        check(s["away"] is True and "locked" in s["why"], "a locked screen means away even with recent input")
        s = status(machine={"idle_seconds": 60, "locked": False, "display_asleep": True})
        check(s["away"] is True and "asleep" in s["why"], "a sleeping display means away")
        s = status(machine={"idle_seconds": None, "locked": None, "display_asleep": None})
        check(s["away"] == "unsure" and s["deliver"] == "both", "no readable signal means unsure, deliver both ways")
        s = status(machine={"idle_seconds": None, "locked": False, "display_asleep": False})
        check(s["away"] == "unsure", "screen on but idle unreadable is still unsure")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "config.json"), "w") as fh:
            json.dump({"away": {"idle_minutes": 20}}, fh)
        s = status(machine=idle)
        check(s["away"] is False and s["config"]["idle_minutes"] == 20, "the idle threshold comes from ~/.mstack/config.json")
        os.remove(os.path.join(home, "config.json"))

        # the agent's hints
        s = status("the user follows this session from another device", machine=active)
        check(s["away"] is True and "hints" in s["why"], "a hint about another device wins over recent input")
        s = status("this is a cloud session", machine=active)
        check(s["away"] is True, "a cloud session hint means away")
        s = status("not sent because the user is at the terminal", machine=idle)
        check(s["away"] is False and "terminal" in s["why"], "a push not sent because the user is at the terminal wins over idle")
        s = status("something unrelated", machine=idle)
        check(s["away"] is True and s["signals"]["hints"][0]["means"] is None, "an unknown hint is ignored")
        s = status("remote control is on", "the user is at the terminal", machine=idle)
        check(s["away"] is True and "no keyboard" in s["why"], "conflicting hints cancel out and the machine decides")

        # the person's words win, and persist in a temp HOME
        out = json.loads(run("set", "away"))
        check(out["ok"] and os.path.exists(os.path.join(home, "away.json")), "set away writes ~/.mstack/away.json")
        s = status("the user is at the terminal", machine=active)
        check(s["away"] is True and "said they were away" in s["why"], "the person's 'away' wins over hints and the machine")
        check(s["signals"]["words"]["active"] and s["signals"]["words"]["until"] > s["signals"]["words"]["at"],
              "an away record carries its expiry")
        run("set", "back")
        rec = json.load(open(os.path.join(home, "away.json")))
        check(rec["state"] == "back", "set back replaces the record")
        s = status(machine=idle)
        check(s["away"] is False and "said they were back" in s["why"], "the person's 'back' wins over the idle signal")
        s = status(machine={"idle_seconds": 60, "locked": True, "display_asleep": False})
        check(s["away"] is True and "locked" in s["why"], "but a locked screen wins over 'back'")
        s = status("the user follows from another device", machine=active)
        check(s["away"] is False, "'back' also wins over an away hint")

        # expiry
        old = (datetime.datetime.now() - datetime.timedelta(hours=9)).isoformat(timespec="seconds")
        words_file(state="away", at=old, until=(datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(timespec="seconds"))
        s = status(machine=active)
        check(s["away"] is False and s["signals"]["words"]["note"] == "expired", "an away record expires (default 8 hours)")
        words_file(state="away", at=old)
        check(status(machine=active)["away"] is False, "an away record without 'until' expires from its time plus 8 hours")
        out = json.loads(run("set", "away", "--hours", "2"))
        check(out["recorded"]["until"] > out["recorded"]["at"], "set away --hours sets a shorter expiry")
        old = (datetime.datetime.now() - datetime.timedelta(minutes=90)).isoformat(timespec="seconds")
        words_file(state="back", at=old)
        s = status(machine=idle)
        check(s["away"] is True and "grace over" in s["signals"]["words"]["note"], "'back' stops holding after 60 minutes")
        words_file(state="nonsense", at="not a time")
        check(status(machine=active)["away"] is False, "a broken words file is ignored")
        os.remove(os.path.join(home, "away.json"))

        # heard: the person's words, classified
        out = json.loads(run("heard", "I'm on my phone now, send me stuff"))
        check(out["means"] == "away" and status(machine=active)["away"] is True, "heard 'on my phone' records away")
        out = json.loads(run("heard", "ok I'm back at my desk"))
        check(out["means"] == "back" and status(machine=idle)["away"] is False, "heard 'back at my desk' records back")
        out = json.loads(run("heard", "please fix the tests"))
        check(out["means"] is None and "recorded" not in out, "other words record nothing")
        check(run("status", "--text", machine=active).startswith("present:"), "status --text gives one line")

        # the session start rule
        start = run("session-start", tool=MSTACK)
        check("away mode" in start and "away.py" in start and "status" in start and "never end with only a local path" in start,
              "the session start rules tell the agent to check away status before presenting outputs")
        routing = run("routing", tool=MSTACK)
        check("away mode" in routing and "file-sending tool" in routing, "the routing block says it for other agents too")

        # render: the Markdown converter needs no Chrome
        page = away_render.markdown_to_html("# Title\n\nSome **bold** text.\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        check("<h1>Title</h1>" in page and "<strong>bold</strong>" in page and "<li>one</li>" in page and "<td>2</td>" in page
              and "color-scheme" in page, "Markdown becomes a light-theme HTML page")
        out = json.loads(run("render", os.path.join(work, "missing.html"), "--out", os.path.join(work, "out"), expect=1))
        check(out["files"] == [] and "no such file" in out["notes"][0], "a missing file is reported plainly")
        with open(os.path.join(work, "data.bin"), "wb") as fh:
            fh.write(b"\x00\x01")
        out = json.loads(run("render", os.path.join(work, "data.bin"), "--out", os.path.join(work, "out"), expect=1))
        check(out["kind"] == "other" and "no renderer" in out["notes"][0], "a file with no renderer says so")
        with open(os.path.join(work, "pic.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        out = json.loads(run("render", os.path.join(work, "pic.png"), "--out", os.path.join(work, "out")))
        check(out["renderer"] == "copy" and out["files"][0]["path"].endswith("pic.png"), "an image is passed through")
        check(run("outbox").strip().startswith(home), "the outbox lives under ~/.mstack")

        # render: a real HTML report to PDF and PNG, when Chrome is present
        sample = os.path.join(work, "report.html")
        with open(sample, "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html><head><meta charset='utf-8'><title>Sample</title></head><body style='font-family:sans-serif'>"
                     "<h1>Design review, round 3</h1><p>Every journey scores 10 out of 10.</p>"
                     "<div style='height:1300px;background:#eef'></div><p>The end.</p></body></html>")
        if away_render.find_chrome():
            out = json.loads(run("render", sample, "--out", os.path.join(work, "out")))
            whats = [f["what"] for f in out["files"]]
            paths = [f["path"] for f in out["files"]]
            check(out["renderer"] == "chrome" and any(p.endswith("report.pdf") for p in paths)
                  and all(f["bytes"] > 0 for f in out["files"]), "an HTML report renders to a PDF")
            check(any(p.endswith("report-phone.png") for p in paths) and any("phone width" in w for w in whats),
                  "and to a phone-width PNG of the first screen")
            check(any(p.endswith("report-phone-full.png") for p in paths), "and a full-page PNG when the page is short")
            with open([p for p in paths if p.endswith("report.pdf")][0], "rb") as fh:
                check(fh.read(5) == b"%PDF-", "the PDF is a real PDF")
            with open([p for p in paths if p.endswith("report-phone.png")][0], "rb") as fh:
                check(fh.read(8) == b"\x89PNG\r\n\x1a\n", "the PNG is a real PNG")
            md = os.path.join(work, "notes.md")
            with open(md, "w") as fh:
                fh.write("# Notes\n\nA line.\n")
            out = json.loads(run("render", md, "--out", os.path.join(work, "out")))
            check(any(p.endswith("notes.html") for p in paths_of(out)) and any(p.endswith("notes.pdf") for p in paths_of(out)),
                  "a Markdown file becomes HTML then PDF")
        else:
            print("SKIPPED  the real render needs Google Chrome or Chromium (set MSTACK_CHROME)")
            out = json.loads(run("render", sample, "--out", os.path.join(work, "out"), expect=0 if sys.platform == "darwin" else 1))
            check(out["files"] or "install Google Chrome" in " ".join(out["notes"]), "without Chrome it falls back or says so plainly")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


def paths_of(out):
    return [f["path"] for f in out["files"]]


if __name__ == "__main__":
    main()
