#!/usr/bin/env python3
"""mStack multi-evaluator loop: one command line tool for people and agents.

Rounds of independent review until every journey scores 10 out of 10. Python 3.9 or later, standard
library only. Every command takes --dir, the review folder that holds mstack-eval.json (default: the
current folder), and every command that reports state can print JSON with --json.

  init         write a starter mstack-eval.json (and the review folder) to fill in
  status       where the loop is and what to do next (--json for agents)
  start-round  open the next round: rounds/r<N>/ with changes.md and this round's criteria
  capture      capture the fixed screens for the round, the same way every round
  brief        write each reviewer's brief for the round (rounds/r<N>/briefs/<reviewer>.md)
  serve        start the product on a port, in a fresh temporary folder, until stopped (for reviewers)
  review       run the command line reviewers (for example Codex) on their briefs, in parallel
  verdict      check a reviewer's JSON verdict and save it to the round (for agent reviewers)
  validate     check a verdict file against the reply format, without saving it
  report       build report.html: score trend, each journey, proposals, before and after, filmstrips
  notify       send a test notification through the configured notify command

Typical round:  start-round, edit changes.md, capture, brief, review (and your own agent's reviewer,
then verdict), report. Repeat until status says every reviewer gives every journey 10.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CONFIG_NAME = "mstack-eval.json"
DRIVER = os.path.join(HERE, "drive.mjs")
SEVERITIES = ("high", "medium", "low")


# ---------------------------------------------------------------- config and rounds

class Project(object):
    def __init__(self, folder):
        self.dir = os.path.abspath(folder)
        path = os.path.join(self.dir, CONFIG_NAME)
        if not os.path.exists(path):
            raise SystemExit("No %s in %s. Run: python3 %s init --dir %s" % (CONFIG_NAME, self.dir, __file__, folder))
        with open(path, encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.rounds_dir = os.path.join(self.dir, "rounds")

    @property
    def name(self):
        return self.cfg.get("name", "Untitled")

    def reviewers(self):
        return self.cfg.get("reviewers", [])

    def reviewer(self, rid):
        return next((r for r in self.reviewers() if r["id"] == rid), None)

    def journeys(self):
        return self.cfg.get("journeys", [])

    def viewports(self):
        vp = {"desktop": {"w": 1440, "h": 1000}, "phone": {"w": 390, "h": 844, "mobile": True}}
        vp.update(self.cfg.get("viewports", {}))
        return vp

    def views(self):
        out = []
        for v in self.cfg.get("views", []):
            v = dict(v)
            if isinstance(v.get("viewport"), str):
                v["viewport"] = self.viewports()[v["viewport"]]
            v.setdefault("viewport", self.viewports()["desktop"])
            v.setdefault("group", "Phone" if v["viewport"].get("mobile") else "Desktop")
            out.append(v)
        return out

    def criteria(self, n=None):
        """The criteria in force: the floor, plus every stage that is active (or active from round n)."""
        crit = [dict(c, stage="Floor") for c in self.cfg.get("criteria", [])]
        for st in self.cfg.get("stages", []):
            on = st.get("active") or (n is not None and st.get("from_round") and n >= st["from_round"])
            if on:
                crit += [dict(c, stage=st.get("name", "Stage")) for c in st.get("criteria", [])]
        return crit

    def round_numbers(self):
        if not os.path.isdir(self.rounds_dir):
            return []
        return sorted(int(m.group(1)) for d in os.listdir(self.rounds_dir) if (m := re.fullmatch(r"r(\d+)", d)))

    def latest(self):
        ns = self.round_numbers()
        return ns[-1] if ns else None

    def rdir(self, n, *parts):
        return os.path.join(self.rounds_dir, "r%d" % n, *parts)

    def need_round(self, n):
        n = n or self.latest()
        if not n or not os.path.isdir(self.rdir(n)):
            raise SystemExit("No round yet. Run: start-round")
        return n

    def verdicts(self, n):
        out = {}
        vdir = self.rdir(n, "verdicts")
        for f in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []:
            if f.endswith(".json"):
                with open(os.path.join(vdir, f), encoding="utf-8") as fh:
                    try:
                        out[f[:-5]] = json.load(fh)
                    except ValueError:
                        pass
        return out

    def shots(self, n):
        sdir = self.rdir(n, "shots")
        if not os.path.isdir(sdir):
            return []
        return sorted(set(f[:-4] for f in os.listdir(sdir) if f.endswith(".png")))


def tmp_base():
    # Chrome on macOS will not start from the per-user system temp folder, so use /tmp there.
    return os.environ.get("MSTACK_TMP") or ("/tmp" if sys.platform == "darwin" else tempfile.gettempdir())


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_free(port):
    """True when nothing is listening on the port (a closed connection waiting to expire does not count)."""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def fill(value, values):
    """Replace {port}, {tmp}, {dir}, {url} and friends in a string, a list or a dict."""
    if isinstance(value, str):
        for k, v in values.items():
            value = value.replace("{%s}" % k, str(v))
        return value
    if isinstance(value, list):
        return [fill(x, values) for x in value]
    if isinstance(value, dict):
        return dict((k, fill(v, values)) for k, v in value.items())
    return value


# ---------------------------------------------------------------- the product under review

class Target(object):
    """Start the product (if it has a start command) in a fresh temporary folder and wait until it answers."""

    def __init__(self, project, override=None, port=None):
        self.p = project
        t = dict(project.cfg.get("target", {}))
        t.update(override or {})
        self.t = t
        self.port = port or free_port()
        self.tmp = tempfile.mkdtemp(prefix="mstack-target-", dir=tmp_base())
        cwd = t.get("cwd", ".")
        self.cwd = cwd if os.path.isabs(cwd) else os.path.normpath(os.path.join(project.dir, cwd))
        self.values = {"port": self.port, "tmp": self.tmp, "dir": project.dir, "cwd": self.cwd}
        self.url = fill(t.get("url", "http://127.0.0.1:{port}/"), self.values)
        self.values["url"] = self.url
        self.proc = None
        self.log = os.path.join(self.tmp, "product.log")

    def tail(self):
        try:
            with open(self.log, encoding="utf-8", errors="replace") as fh:
                return "\nIts last output:\n" + "".join(fh.readlines()[-15:])
        except OSError:
            return ""

    def _run(self, cmd, wait):
        env = dict(os.environ)
        env.update(fill(self.t.get("env", {}), self.values))
        shell = isinstance(cmd, str)
        kw = dict(cwd=self.cwd, env=env, shell=shell, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "posix":
            kw["start_new_session"] = True
        if wait:
            kw["stdout"] = kw["stderr"] = subprocess.PIPE
            r = subprocess.run(fill(cmd, self.values), timeout=600, **kw)
            if r.returncode != 0:
                raise SystemExit("A setup command failed: %s\n%s" % (cmd, (r.stderr or b"").decode(errors="replace")))
            return None
        kw["stdout"] = open(self.log, "w")
        kw["stderr"] = subprocess.STDOUT
        return subprocess.Popen(fill(cmd, self.values), **kw)

    def start(self):
        if self.t.get("start") and not port_free(self.port):
            self.stop()
            raise SystemExit("Port %d is already in use. Stop whatever is using it, or choose another port." % self.port)
        for cmd in self.t.get("setup", []):
            self._run(cmd, wait=True)
        if self.t.get("start"):
            self.proc = self._run(self.t["start"], wait=False)
        deadline = time.time() + float(self.t.get("ready_timeout", 30))
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a system proxy
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                msg = "The product stopped while starting (exit %s): %s%s" % (self.proc.returncode, self.t["start"], self.tail())
                self.stop()
                raise SystemExit(msg)
            try:
                direct.open(self.url, timeout=2)
                return self
            except urllib.error.HTTPError:
                return self                     # it answered, even if not with 200
            except Exception:
                time.sleep(0.3)
        msg = "The product did not answer at %s within %ss.%s" % (self.url, self.t.get("ready_timeout", 30), self.tail())
        self.stop()
        raise SystemExit(msg)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(self.proc.pid, signal.SIGTERM)
                else:
                    self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()


def drive(spec, out, env=None, timeout=180):
    with open(os.path.join(out, "steps.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh)
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js 18 or later is needed (https://nodejs.org).")
    r = subprocess.run([node, DRIVER, os.path.join(out, "steps.json"), os.path.join(out, "run")], capture_output=True,
                       text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise SystemExit("The journey driver failed: %s %s" % (r.stdout.strip(), r.stderr.strip()))
    return os.path.join(out, "run")


# ---------------------------------------------------------------- commands

def cmd_init(args):
    folder = os.path.abspath(args.dir)
    path = os.path.join(folder, CONFIG_NAME)
    if os.path.exists(path) and not args.force:
        raise SystemExit("%s already exists (use --force to replace it)" % path)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(SKILL, "templates", CONFIG_NAME), encoding="utf-8") as fh:
        cfg = json.load(fh)
    if args.name:
        cfg["name"] = args.name
    if args.url:
        cfg["target"] = {"url": args.url}
    if args.start:
        cfg["target"] = {"url": args.start_url or "http://127.0.0.1:{port}/", "start": args.start, "cwd": args.cwd or "."}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    say(args, {"ok": True, "config": path,
               "next": "Fill in about, journeys and views in %s, then run start-round" % path})


def say(args, data, text=None):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        print(text if text is not None else "\n".join("%s: %s" % (k, v) for k, v in data.items()))


def round_state(p, n):
    v = p.verdicts(n)
    want = [r["id"] for r in p.reviewers()]
    jids = [j["id"] for j in p.journeys()]
    scores = dict((who, dict((j["id"], j.get("score")) for j in d.get("journeys", []))) for who, d in v.items())
    briefs = p.rdir(n, "briefs")
    return {
        "round": n,
        "shots": len(p.shots(n)),
        "briefs": sorted(f[:-3] for f in os.listdir(briefs) if f.endswith(".md")) if os.path.isdir(briefs) else [],
        "verdicts": sorted(v),
        "missing_verdicts": [w for w in want if w not in v],
        "overall": dict((who, d.get("overall")) for who, d in v.items()),
        "scores": scores,
        "all_ten": bool(want) and all(w in v for w in want) and all(
            scores.get(w, {}).get(j) == 10 for w in want for j in jids),
    }


def next_step(p):
    n = p.latest()
    if not p.journeys():
        return "Add journeys (and views) to %s" % os.path.join(p.dir, CONFIG_NAME)
    if n is None:
        return "start-round (round 1 is the starting point)"
    st = round_state(p, n)
    if st["shots"] == 0 and p.views():
        return "capture --round %d" % n
    if len(st["briefs"]) < len(p.reviewers()):
        return "brief --round %d" % n
    if st["missing_verdicts"]:
        parts = []
        for rid in st["missing_verdicts"]:
            r = p.reviewer(rid) or {}
            if r.get("kind") == "command":
                parts.append("review --round %d --only %s" % (n, rid))
            else:
                parts.append("give %s to a fresh %s reviewer, then: verdict --round %d --reviewer %s <reply.json>" % (
                    p.rdir(n, "briefs", rid + ".md"), r.get("name", rid), n, rid))
        return "; ".join(parts)
    report = os.path.join(p.dir, "report.html")
    newest = max(os.path.getmtime(os.path.join(p.rdir(n, "verdicts"), f)) for f in os.listdir(p.rdir(n, "verdicts")))
    if not os.path.exists(report) or os.path.getmtime(report) < newest:
        return "report"
    if st["all_ten"]:
        return ("done: every reviewer gives every journey 10. Now test with real first-time people "
                "(record what happened in rounds/r%d/people.md); where they disagree with the AI reviewers, the people win." % n)
    return "fix the reviewers' proposals in the product, then start-round"


def cmd_status(args):
    p = Project(args.dir)
    n = p.latest()
    data = {"project": p.name, "dir": p.dir, "round": n,
            "reviewers": [dict(id=r["id"], name=r.get("name", r["id"]), kind=r.get("kind", "agent")) for r in p.reviewers()],
            "journeys": [dict(id=j["id"], name=j["name"]) for j in p.journeys()],
            "criteria": [c["name"] for c in p.criteria(n)],
            "rounds": [round_state(p, k) for k in p.round_numbers()],
            "next": next_step(p)}
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print("%s: round %s" % (p.name, n if n else "none yet"))
    for r in data["rounds"]:
        print("  round %d: %d screens, verdicts from %s%s" % (
            r["round"], r["shots"], ", ".join(r["verdicts"]) or "nobody yet",
            "; overall " + ", ".join("%s %s" % kv for kv in r["overall"].items()) if r["overall"] else ""))
    print("next: " + data["next"])


def cmd_start_round(args):
    p = Project(args.dir)
    n = (p.latest() or 0) + 1
    os.makedirs(p.rdir(n, "verdicts"), exist_ok=True)
    changes = p.rdir(n, "changes.md")
    if not os.path.exists(changes):
        with open(changes, "w", encoding="utf-8") as fh:
            fh.write("# Round %d\n\n%s\n" % (n, "- The starting point: nothing changed yet." if n == 1 else
                                              "- (What changed going into this round, one bullet each.)"))
    with open(p.rdir(n, "criteria.json"), "w", encoding="utf-8") as fh:
        json.dump(p.criteria(n), fh, indent=2)
    say(args, {"round": n, "changes": changes, "next": "edit changes.md, then capture --round %d" % n})


def cmd_capture(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    out = p.rdir(n, "shots")
    os.makedirs(out, exist_ok=True)
    only = set(filter(None, (args.only or "").split(",")))
    results = []
    views = p.views()
    with open(p.rdir(n, "views.json"), "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2)
    for v in views:
        if only and v["id"] not in only:
            continue
        work = tempfile.mkdtemp(prefix="mstack-capture-", dir=tmp_base())
        try:
            with Target(p, v.get("target")) as t:
                steps = fill(v.get("steps") or [{"do": "goto", "url": "{url}"}], dict(t.values, app=t.url))
                spec = {"viewport": v["viewport"], "scheme": v.get("scheme", "light"), "steps": steps,
                        "thumb": 640 if v["viewport"]["w"] > 600 else 300}
                run = drive(spec, work)
            pngs = sorted(f for f in os.listdir(run) if f.endswith(".png"))
            shutil.copyfile(os.path.join(run, pngs[-1]), os.path.join(out, v["id"] + ".png"))
            if os.path.exists(os.path.join(run, "final.jpg")):
                shutil.copyfile(os.path.join(run, "final.jpg"), os.path.join(out, v["id"] + ".jpg"))
            with open(os.path.join(run, "log.txt"), encoding="utf-8") as fh:
                log = fh.read()
            with open(os.path.join(out, v["id"] + ".txt"), "w", encoding="utf-8") as fh:
                fh.write(log)
            ok = "NOT FOUND" not in log
            results.append({"view": v["id"], "ok": ok})
            if not args.json:
                print("%-24s %s" % (v["id"], "ok" if ok else "captured, but a step did not find its target"), flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if args.json:
        print(json.dumps({"round": n, "shots": out, "views": results}, indent=2))


REPLY_FORMAT = """{"reviewer": "%(rid)s", "round": %(n)d,
 "journeys": [{"id": <journey id>, "name": "...", "score": <0 to 10>,
   "if_fixed": <0 to 10: the score if your fixes for this journey were made>,
   "what_worked": ["..."],
   "fixes": [{"severity": "high|medium|low", "where": "screen or element", "problem": "...", "fix": "..."}]}],
 "overall": <0 to 10>,
 "top_fixes": ["the five changes that would raise the scores most"],
 "broken": ["anything that errored, did nothing, or showed wrong data"]}"""


def brief_text(p, n, rid, index, cdp_port=None):
    r = p.reviewer(rid) or {"id": rid}
    port = 8900 + 10 * index
    target = p.cfg.get("target", {})
    me = os.path.abspath(__file__)
    lines = ["# %s: independent design review, round %d" % (p.name, n), "",
             "You are an independent, demanding reviewer. You have never seen this product. Judge it as this person: "
             "%s Be specific and sceptical: a 10 means you could not find anything to improve for that journey. "
             "Do not be polite; be useful." % p.cfg.get("persona", "a first-time user who is not technical."), "",
             "## What it is", "", p.cfg.get("about", "(No description given.)"), "",
             "## Set up", ""]
    if target.get("start"):
        lines += ["1. Start your own copy of the product on your own port, in the background (it runs in a fresh "
                  "temporary folder and stops when you stop it):",
                  "   `python3 %s serve --dir %s --port %d`" % (shlex.quote(me), shlex.quote(p.dir), port),
                  "   It prints `ready: <address>` when it answers. Use that address in your steps."]
    else:
        lines += ["1. The product is at %s. Use it as a visitor would; never submit real payments, messages or "
                  "personal data." % fill(target.get("url", ""), {"port": port})]
    lines += ["2. Drive it with the journey driver, a real headless Chrome that saves a screenshot and the visible text "
              "after every step:",
              "   `node %s <steps.json> <out-folder>`" % shlex.quote(DRIVER),
              "   Read the top of that file for the step format. Write one steps file per journey and screen size, and "
              "keep your files in %s. Look at the screenshots (open the PNG files) as well as reading log.txt."
              % p.rdir(n, "work", rid)]
    if cdp_port:
        lines += ["   If your sandbox cannot start Chrome, one is already running for you: put `MSTACK_CDP_PORT=%d` in "
                  "front of the node command." % cdp_port]
    lines += ["3. Stop anything you started when you finish. Never change the product's own files.",
              "4. Work alone. Do not read other reviewers' briefs, work folders or verdicts, earlier verdicts, or "
              "report.html: your scores must be your own.", "",
              "## The journeys for this round (score each 0 to 10)", ""]
    for j in p.journeys():
        vp = j.get("viewport")
        lines.append("%s. **%s%s.** %s" % (j["id"], j["name"], " (%s)" % vp if vp else "", j.get("task", "")))
    lines += ["", "## Score each journey on", "",
              "A journey only scores 10 when it meets every one of these.", ""]
    for c in p.criteria(n):
        lines.append("- **%s**: %s" % (c["name"], c.get("means", "")))
    lines += ["", "## Before and after", ""]
    prev = [k for k in p.round_numbers() if k < n and p.shots(k)]
    if prev:
        lines.append("Last round's screenshots of the same screens are in %s, and this round's are in %s. Compare them: "
                     "say what improved, what got worse, and what is still in the way." % (
                         p.rdir(prev[-1], "shots"), p.rdir(n, "shots")))
    else:
        lines.append("This is the first round. This round's fixed screenshots are in %s." % p.rdir(n, "shots"))
    lines += ["", "## Reply format", "", "Return JSON only, with every journey scored:", "",
              REPLY_FORMAT % {"rid": rid, "n": n}, ""]
    return "\n".join(lines)


def cmd_brief(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    os.makedirs(p.rdir(n, "briefs"), exist_ok=True)
    written = []
    for i, r in enumerate(p.reviewers()):
        os.makedirs(p.rdir(n, "work", r["id"]), exist_ok=True)
        cdp = args.cdp_port if r.get("shared_chrome") else None
        path = p.rdir(n, "briefs", r["id"] + ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(brief_text(p, n, r["id"], i, cdp_port=cdp))
        written.append(path)
    say(args, {"round": n, "briefs": written}, "\n".join(written))


def cmd_serve(args):
    p = Project(args.dir)
    t = Target(p, port=args.port)

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)          # a plain kill still stops the product too
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop)
    t.start()
    print("ready: %s" % t.url, flush=True)
    try:
        while t.proc is None or t.proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        t.stop()


def find_chrome():
    if os.environ.get("MSTACK_CHROME"):
        return os.environ["MSTACK_CHROME"]
    places = {"darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                         "/Applications/Chromium.app/Contents/MacOS/Chromium"],
              "win32": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]}.get(sys.platform, [])
    for x in places:
        if os.path.exists(x):
            return x
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def shared_chrome(port):
    """A headless Chrome that sandboxed reviewers reach through MSTACK_CDP_PORT."""
    bin_ = find_chrome()
    if not bin_:
        return None, None
    work = tempfile.mkdtemp(prefix="mstack-shared-chrome-", dir=tmp_base())
    proc = subprocess.Popen([bin_, "--headless=new", "--remote-debugging-port=%d" % port, "--user-data-dir=" + work,
                             "--hide-scrollbars", "--no-first-run"] + os.environ.get("MSTACK_CHROME_ARGS", "").split()
                            + ["about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    return proc, work


def extract_json(text):
    text = text.strip()
    for cand in [text] + re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            return json.loads(cand)
        except ValueError:
            pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            pass
    return None


def check_verdict(p, v, rid=None, n=None):
    """Problems with a verdict, as plain sentences (an empty list means it is fine)."""
    if not isinstance(v, dict):
        return ["The reply is not a JSON object."]
    probs = []
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 10   # noqa: E731
    if rid and v.get("reviewer") not in (rid, None):
        probs.append("reviewer is %r, expected %r." % (v.get("reviewer"), rid))
    if n is not None and v.get("round") not in (n, None):
        probs.append("round is %r, expected %d." % (v.get("round"), n))
    if not num(v.get("overall")):
        probs.append("overall must be a number from 0 to 10.")
    js = v.get("journeys")
    if not isinstance(js, list) or not js:
        return probs + ["journeys must be a list with every journey scored."]
    seen = set()
    for j in js:
        if not isinstance(j, dict):
            probs.append("each journey must be an object.")
            continue
        jid = j.get("id")
        seen.add(jid)
        if not num(j.get("score")):
            probs.append("journey %s: score must be a number from 0 to 10." % jid)
        if not num(j.get("if_fixed")):
            probs.append("journey %s: if_fixed must be a number from 0 to 10." % jid)
        for f in j.get("fixes", []) or []:
            if not isinstance(f, dict) or f.get("severity") not in SEVERITIES or not f.get("fix"):
                probs.append("journey %s: each fix needs a severity (high, medium or low) and a fix." % jid)
                break
    missing = [j["id"] for j in p.journeys() if j["id"] not in seen]
    if missing:
        probs.append("journeys not scored: %s." % ", ".join(str(m) for m in missing))
    for k in ("top_fixes", "broken"):
        if k in v and not isinstance(v[k], list):
            probs.append("%s must be a list." % k)
    return probs


def save_verdict(p, n, rid, v):
    v.setdefault("reviewer", rid)
    v.setdefault("round", n)
    v.setdefault("top_fixes", [])
    v.setdefault("broken", [])
    os.makedirs(p.rdir(n, "verdicts"), exist_ok=True)
    path = p.rdir(n, "verdicts", rid + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2, ensure_ascii=False)
    return path


def run_reviewer(p, n, r, cdp_port, results):
    rid = r["id"]
    work = p.rdir(n, "work", rid)
    os.makedirs(work, exist_ok=True)
    reply = os.path.join(work, "reply.txt")
    if os.path.exists(reply):
        os.remove(reply)
    brief = p.rdir(n, "briefs", rid + ".md")
    with open(brief, encoding="utf-8") as fh:
        text = fh.read()
    values = {"work": work, "reply": reply, "brief": brief, "dir": p.dir, "round": n, "skill": SKILL}
    cmd = fill(r["command"], values)
    env = dict(os.environ)
    if cdp_port:
        env["MSTACK_CDP_PORT"] = str(cdp_port)
    started = time.time()
    try:
        proc = subprocess.run(cmd, input=text if r.get("stdin", "brief") == "brief" else None, capture_output=True,
                              text=True, env=env, cwd=work, shell=isinstance(cmd, str),
                              timeout=60 * float(r.get("timeout_minutes", 60)))
        out = proc.stdout
    except subprocess.TimeoutExpired:
        results[rid] = {"ok": False, "problem": "timed out"}
        return
    except FileNotFoundError as e:
        results[rid] = {"ok": False, "problem": "could not run %s: %s" % (cmd[0] if isinstance(cmd, list) else cmd, e)}
        return
    raw = out
    if os.path.exists(reply):
        with open(reply, encoding="utf-8") as fh:
            raw = fh.read() or out
    with open(os.path.join(work, "raw-reply.txt"), "w", encoding="utf-8") as fh:
        fh.write(raw)
    v = extract_json(raw)
    probs = check_verdict(p, v, rid, n)
    if probs:
        results[rid] = {"ok": False, "problem": "the reply did not fit the format: " + " ".join(probs),
                        "raw": os.path.join(work, "raw-reply.txt"), "exit": proc.returncode}
        return
    results[rid] = {"ok": True, "verdict": save_verdict(p, n, rid, v), "overall": v["overall"],
                    "minutes": round((time.time() - started) / 60, 1)}


def cmd_review(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    only = set(filter(None, (args.only or "").split(",")))
    chosen = [r for r in p.reviewers() if (not only or r["id"] in only)]
    for r in chosen:
        if not os.path.exists(p.rdir(n, "briefs", r["id"] + ".md")):
            raise SystemExit("No brief for %s yet. Run: brief --round %d" % (r["id"], n))
    runnable = [r for r in chosen if r.get("kind") == "command"]
    agents = [r for r in chosen if r.get("kind") != "command"]
    chrome = work = None
    if any(r.get("shared_chrome") for r in runnable):
        chrome, work = shared_chrome(args.cdp_port)
    results = {}
    try:
        threads = [threading.Thread(target=run_reviewer, args=(p, n, r, args.cdp_port if r.get("shared_chrome") else None,
                                                               results)) for r in runnable]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        if chrome:
            chrome.kill()
            shutil.rmtree(work, ignore_errors=True)
    for r in agents:
        results[r["id"]] = {"ok": None, "waiting": "your agent runs this reviewer: give it %s in fresh context, then "
                                                   "run verdict --round %d --reviewer %s <reply>" % (
                                                       p.rdir(n, "briefs", r["id"] + ".md"), n, r["id"])}
    if args.json:
        print(json.dumps({"round": n, "results": results}, indent=2))
    else:
        for rid, res in results.items():
            if res.get("ok"):
                print("%s: overall %s, saved %s" % (rid, res["overall"], res["verdict"]))
            elif res.get("ok") is None:
                print("%s: %s" % (rid, res["waiting"]))
            else:
                print("%s: FAILED, %s" % (rid, res["problem"]))
    if any(res.get("ok") is False for res in results.values()):
        sys.exit(1)


def read_input(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def cmd_verdict(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    if not p.reviewer(args.reviewer):
        raise SystemExit("No reviewer %r in %s" % (args.reviewer, CONFIG_NAME))
    v = extract_json(read_input(args.file))
    probs = check_verdict(p, v, args.reviewer, n)
    if probs:
        say(args, {"ok": False, "problems": probs}, "Not saved:\n- " + "\n- ".join(probs))
        sys.exit(1)
    say(args, {"ok": True, "saved": save_verdict(p, n, args.reviewer, v), "next": next_step(p)})


def cmd_validate(args):
    p = Project(args.dir)
    probs = check_verdict(p, extract_json(read_input(args.file)))
    say(args, {"ok": not probs, "problems": probs}, "fits the reply format" if not probs else "- " + "\n- ".join(probs))
    sys.exit(1 if probs else 0)


def notify(p, message):
    cmd = (p.cfg.get("notify") or {}).get("command")
    if not cmd:
        return False
    try:
        subprocess.run(fill(cmd, {"message": message}), shell=isinstance(cmd, str), timeout=30, capture_output=True)
        return True
    except Exception:
        return False


def cmd_report(args):
    sys.path.insert(0, HERE)
    import report
    p = Project(args.dir)
    path, summary = report.build(p)
    sent = notify(p, summary) if not args.no_notify else False
    say(args, {"report": path, "summary": summary, "notified": sent, "next": next_step(p)})


def cmd_notify(args):
    p = Project(args.dir)
    ok = notify(p, args.message)
    say(args, {"sent": ok}, "sent" if ok else "No notify command in %s (see docs)" % CONFIG_NAME)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn, round_=True, json_=True):
        s = sub.add_parser(name)
        s.add_argument("--dir", default=".", help="the review folder that holds %s" % CONFIG_NAME)
        if round_:
            s.add_argument("--round", type=int, help="the round (default: the latest)")
        if json_:
            s.add_argument("--json", action="store_true", help="print machine readable JSON")
        s.set_defaults(fn=fn)
        return s

    s = add("init", cmd_init, round_=False)
    s.add_argument("--name")
    s.add_argument("--url", help="review a product that is already running at this address")
    s.add_argument("--start", help="the command that starts the product; {port} is filled in")
    s.add_argument("--start-url", help="its address, with {port} (default http://127.0.0.1:{port}/)")
    s.add_argument("--cwd", help="the folder to run the start command in, relative to the review folder")
    s.add_argument("--force", action="store_true")
    add("status", cmd_status, round_=False)
    add("start-round", cmd_start_round, round_=False)
    s = add("capture", cmd_capture)
    s.add_argument("--only", help="comma separated view ids")
    s = add("brief", cmd_brief)
    s.add_argument("--cdp-port", type=int, default=9555, help="the shared Chrome port for sandboxed reviewers")
    s = add("serve", cmd_serve, round_=False, json_=False)
    s.add_argument("--port", type=int, help="the port to serve on (default: any free port)")
    s = add("review", cmd_review)
    s.add_argument("--only", help="comma separated reviewer ids")
    s.add_argument("--cdp-port", type=int, default=9555)
    s = add("verdict", cmd_verdict)
    s.add_argument("--reviewer", required=True)
    s.add_argument("file", nargs="?", default="-", help="the reply (a file, or - for standard input)")
    s = add("validate", cmd_validate, round_=False)
    s.add_argument("file", nargs="?", default="-")
    s = add("report", cmd_report, round_=False)
    s.add_argument("--no-notify", action="store_true")
    s = add("notify", cmd_notify, round_=False)
    s.add_argument("message", nargs="?", default="mStack: test notification")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
