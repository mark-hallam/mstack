#!/usr/bin/env python3
"""mStack multi-evaluator loop: one command line tool for people and agents.

Rounds of independent review until the product is ready for real people: every journey 9 or better from
every reviewer, no high-severity fix open, reviewers within a point, held for two rounds (readiness.py).
Python 3.9 or later, standard library only. Every command takes --dir, the review folder that holds mstack-eval.json (default: the
current folder), and every command that reports state can print JSON with --json.

  init         write a starter mstack-eval.json (and the review folder) to fill in
  status       where the loop is and what to do next (--json for agents)
  start-round  open the next round: rounds/r<N>/ with changes.md and this round's criteria
  capture      capture the fixed screens for the round, the same way every round
  brief        write each reviewer's blind scoring brief (rounds/r<N>/briefs/<reviewer>.md) and, from
               round 2, a separate comparison brief (<reviewer>-compare.md) to give after the verdict
  serve        start the product on a port, in a fresh temporary folder, until stopped (for reviewers)
  review       run the command line reviewers (for example Codex) on their briefs, in parallel
  verdict      check a reviewer's JSON verdict and save it to the round (for agent reviewers);
               --compare saves the comparison pass apart from the score of record
  validate     check a verdict file against the reply format, without saving it
  report       build report.html: score trend, each journey, proposals, before and after, filmstrips
  notify       send a test notification through the configured notify command

Typical round:  start-round, edit changes.md, capture, brief, review (and your own agent's reviewer,
then verdict), report. Repeat until status says "ready for people".
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
sys.path.insert(0, HERE)
import readiness  # noqa: E402  (the stopping rule, the noise check and "do these next")
import briefs  # noqa: E402  (the scoring brief, blind, and the separate comparison brief)

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
            if f.endswith(".json") and not f.endswith(".compare.json"):
                with open(os.path.join(vdir, f), encoding="utf-8") as fh:
                    try:
                        out[f[:-5]] = json.load(fh)
                    except ValueError:
                        pass
        return out

    def comparisons(self, n):
        """The separate comparison passes (<reviewer>.compare.json), never mixed with the scores of record."""
        out = {}
        vdir = self.rdir(n, "verdicts")
        for f in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []:
            if f.endswith(".compare.json"):
                with open(os.path.join(vdir, f), encoding="utf-8") as fh:
                    try:
                        out[f[:-len(".compare.json")]] = json.load(fh)
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
        env = dict(os.environ, PYTHONUNBUFFERED="1")             # so a Python product's output shows up at once
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


round_state = readiness.round_state
next_step = readiness.next_step


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
    frozen = freeze_control(p, n)
    if args.json:
        print(json.dumps({"round": n, "shots": out, "views": results, "control": frozen}, indent=2))
    elif frozen:
        print("control frozen from this round's screens: %s" % frozen, flush=True)


def freeze_control(p, n):
    """The noise check: the first captured round's screens are copied to <dir>/control/ and never change.
    Every round, each reviewer scores them as journey "control"; how far that score moves is noise."""
    if not p.cfg.get("control"):
        return None
    cdir = os.path.join(p.dir, readiness.CONTROL)
    if os.path.isdir(cdir):
        return None
    sdir = p.rdir(n, "shots")
    if not os.path.isdir(sdir) or not p.shots(n):
        return None
    os.makedirs(cdir)
    for f in os.listdir(sdir):
        if f.endswith((".png", ".txt", ".jpg")):
            shutil.copyfile(os.path.join(sdir, f), os.path.join(cdir, f))
    with open(os.path.join(cdir, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Control (frozen from round %d)\n\nThese screens never change. Every round each reviewer scores them "
                 "as journey \"control\". How far that score moves between rounds is the reviewer's noise: a change in "
                 "a real journey smaller than that is not evidence of improvement.\n" % n)
    return cdir


def cmd_brief(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    kinds = set(r.get("kind", "agent") for r in p.reviewers())
    if p.reviewers() and kinds <= {"chat"}:
        raise SystemExit("Every reviewer is a web chat. A chat reviewer only sees screenshots, so it is a tie breaker: "
                         "add at least one reviewer of kind agent or command that drives the real product.")
    os.makedirs(p.rdir(n, "briefs"), exist_ok=True)
    prev = [k for k in p.round_numbers() if k < n and p.shots(k)]
    written = []
    for i, r in enumerate(p.reviewers()):
        os.makedirs(p.rdir(n, "work", r["id"]), exist_ok=True)
        cdp = args.cdp_port if r.get("shared_chrome") else None
        path = p.rdir(n, "briefs", r["id"] + ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(briefs.scoring_brief(p, n, r["id"], i, cdp_port=cdp))
        written.append(path)
        if prev:
            cpath = p.rdir(n, "briefs", r["id"] + "-compare.md")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(briefs.compare_brief(p, n, r["id"], prev[-1]))
            written.append(cpath)
    note = ("The scoring briefs are blind (no earlier rounds). Give a -compare brief to a reviewer only after its "
            "verdict is saved, and save that reply with: verdict --compare" if prev else "")
    say(args, {"round": n, "briefs": written, "note": note}, "\n".join(written) + ("\n" + note if note else ""))


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
        fixes = j.get("fixes", []) or []
        if not num(j.get("score")):
            probs.append("journey %s: score must be a number from 0 to 10." % jid)
        if not num(j.get("if_fixed")):
            probs.append("journey %s: if_fixed must be a number from 0 to 10 (the score if your fixes were made)." % jid)
        elif num(j.get("score")) and j["if_fixed"] < j["score"]:
            probs.append("journey %s: if_fixed (%s) cannot be below the score (%s)." % (jid, j["if_fixed"], j["score"]))
        if j.get("score") == 10 and fixes:
            probs.append("journey %s: a 10 means nothing is left to improve, but %d fix%s proposed; lower the score or drop the fixes."
                         % (jid, len(fixes), " is" if len(fixes) == 1 else "es are"))
        for f in fixes:
            if not isinstance(f, dict) or f.get("severity") not in SEVERITIES or not f.get("fix"):
                probs.append("journey %s: each fix needs a severity (high, medium or low) and a fix." % jid)
                break
    missing = [j["id"] for j in p.journeys() if j["id"] not in seen]
    if p.cfg.get("control") and readiness.CONTROL not in seen:
        missing.append(readiness.CONTROL)
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
    r = p.reviewer(rid) or {}
    v["via"] = r.get("kind", "agent")
    v["saw"] = "live" if r.get("kind") != "chat" or briefs.public_url(p) else "screenshots"
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
        if r.get("kind") == "chat":
            results[r["id"]] = {"ok": None, "waiting": chat_instructions(p, n, r)}
        else:
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


def chat_instructions(p, n, r):
    """What the agent does for a web chat reviewer: the person's own signed-in browser, a new private chat,
    nothing uploaded without their yes."""
    url = briefs.public_url(p)
    shots = ", ".join("%s.png" % s for s in p.shots(n)) or "the fixed screens"
    return ("a web chat reviewer, opt in: with the person's yes on what may be shared, open a new private (temporary) "
            "chat with %s%s in their own signed-in browser, paste %s%s, wait for the reply, save it to a file, close "
            "the tab, then run verdict --round %d --reviewer %s <reply>. It %s, so it is a tie breaker and never counts "
            "toward ready for people." % (
                r.get("name", r["id"]), " at %s" % r["url"] if r.get("url") else "", p.rdir(n, "briefs", r["id"] + ".md"),
                "" if url else " and upload %s from %s (the person decides whether those screens may go to a third party)" % (
                    shots, p.rdir(n, "shots")),
                n, r["id"], "sees the public address and the screens" if url else "sees only screenshots"))


def read_input(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def save_comparison(p, n, rid, v):
    os.makedirs(p.rdir(n, "verdicts"), exist_ok=True)
    path = p.rdir(n, "verdicts", rid + ".compare.json")
    v.setdefault("reviewer", rid)
    v.setdefault("round", n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2, ensure_ascii=False)
    return path


def cmd_verdict(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    if not p.reviewer(args.reviewer):
        raise SystemExit("No reviewer %r in %s" % (args.reviewer, CONFIG_NAME))
    v = extract_json(read_input(args.file))
    if args.compare:
        probs = []
        if not isinstance(v, dict) or not isinstance(v.get("compare"), dict):
            probs.append("a comparison reply is a JSON object with a \"compare\" object (improved, regressed, unchanged).")
        elif args.reviewer not in p.verdicts(n):
            probs.append("save %s's verdict for round %d first: the comparison pass comes after the score of record." % (args.reviewer, n))
        if probs:
            say(args, {"ok": False, "problems": probs}, "Not saved:\n- " + "\n- ".join(probs))
            sys.exit(1)
        say(args, {"ok": True, "saved": save_comparison(p, n, args.reviewer, v), "next": next_step(p)})
        return
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
    s.add_argument("--compare", action="store_true", help="save the separate comparison pass, not a score")
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
