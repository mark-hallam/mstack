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
  meta-brief   write the critique-check brief for each reviewer with a saved verdict
               (rounds/r<N>/briefs/<reviewer>-meta.md): a separate checker re-tests its findings
  meta         check a critique check (rounds/r<N>/meta/<reviewer>.json) and save it
  report       build report.html: score trend, each journey, proposals, before and after, filmstrips
  notify       send a test notification through the configured notify command

Typical round:  start-round, edit changes.md, capture, brief, review (and your own agent's reviewer,
then verdict), meta-brief and the checker's meta, report. Repeat until status says "ready for people".
verdict, meta and report also record the round on the private evaluator scoreboard (evalboard.py).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_LOCKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "mstack", "scripts")
if _LOCKS not in sys.path:
    sys.path.insert(0, _LOCKS)
import locks  # noqa: E402
import readiness  # noqa: E402  (the stopping rule, the noise check and "do these next")
import briefs  # noqa: E402  (the scoring brief, blind, and the separate comparison brief)
import audit  # noqa: E402  (the measured audit that capture saves for every view)
from eval_common import (  # noqa: E402
    CONFIG_NAME,
    SKILL,
    JsonParser,
    fill,
    port_free,
    product_build,
    round_build,
    run_cli,
    tmp_base,
)
from serving import cmd_serve, find_chrome, shared_chrome  # noqa: E402
from target import Target, drive  # noqa: E402
from verdicts import cmd_validate, cmd_verdict, run_reviewer  # noqa: E402
from critique import auto_record, cmd_meta, cmd_meta_brief  # noqa: E402


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

    def enabled_reviewers(self):
        return [r for r in self.reviewers() if r.get("enabled", True) is not False]

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
    rounds = []
    for k in p.round_numbers():
        st = round_state(p, k)
        b = round_build(p, k)
        if b is not None:
            st = dict(st)
            st["build"] = b
        rounds.append(st)
    data = {"project": p.name, "dir": p.dir, "round": n,
            "reviewers": [dict(id=r["id"], name=r.get("name", r["id"]), kind=r.get("kind", "agent")) for r in p.reviewers()],
            "journeys": [dict(id=j["id"], name=j["name"]) for j in p.journeys()],
            "criteria": [c["name"] for c in p.criteria(n)],
            "rounds": rounds,
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
    build = product_build((p.cfg.get("target") or {}).get("cwd"))
    with open(p.rdir(n, "views.json"), "w", encoding="utf-8") as fh:
        json.dump({"views": views, "build": build}, fh, indent=2)
    for v in views:
        if only and v["id"] not in only:
            continue
        work = tempfile.mkdtemp(prefix="mstack-capture-", dir=tmp_base())
        try:
            with Target(p, v.get("target")) as t:
                steps = fill(v.get("steps") or [{"do": "goto", "url": "{url}"}], dict(t.values, app=t.url))
                steps = steps + [{"do": "audit"}]       # measured after the view's own steps
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
            measured = audit.read_run(run)               # None when the audit step failed; capture still succeeds
            if measured is not None:
                shutil.copyfile(os.path.join(run, "audit.json"), os.path.join(out, v["id"] + ".audit.json"))
            results.append({"view": v["id"], "ok": ok, "audit": measured})
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
    active = p.enabled_reviewers()
    kinds = set(r.get("kind", "agent") for r in active)
    if active and kinds <= {"chat"}:
        raise SystemExit("Every reviewer is a web chat. A chat reviewer only sees screenshots, so it is a tie breaker: "
                         "add at least one reviewer of kind agent or command that drives the real product.")
    briefs.check_personas(p)
    os.makedirs(p.rdir(n, "briefs"), exist_ok=True)
    prev = [k for k in p.round_numbers() if k < n and p.shots(k)]
    written = []
    for i, r in enumerate(active):
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


def cmd_review(args):
    p = Project(args.dir)
    n = p.need_round(args.round)
    only = set(filter(None, (args.only or "").split(",")))
    chosen = [r for r in p.enabled_reviewers() if (not only or r["id"] in only)]
    for r in chosen:
        if not os.path.exists(p.rdir(n, "briefs", r["id"] + ".md")):
            raise SystemExit("No brief for %s yet. Run: brief --round %d" % (r["id"], n))
    runnable = [r for r in chosen if r.get("kind") == "command"]
    agents = [r for r in chosen if r.get("kind") != "command"]
    chrome = work = None
    needs_chrome = any(r.get("shared_chrome") for r in runnable)
    wait_sec = 60 * max(float(r.get("timeout_minutes", 60)) for r in runnable) if runnable else 60
    got_chrome = True
    if needs_chrome:
        got_chrome = locks.acquire("chrome", "multi-evaluator review", wait=wait_sec)
        if not got_chrome:
            held = locks.holder("chrome") or {}
            raise SystemExit("review gave up: chrome is still held by %s since %s" % (held.get("owner", "?"), held.get("since", "?")))
    try:
        if needs_chrome:
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
    finally:
        if needs_chrome and got_chrome:
            locks.release("chrome")
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
    say(args, {"report": path, "summary": summary, "notified": sent, "scoreboard": auto_record(p, p.latest()),
               "next": next_step(p)})


def cmd_notify(args):
    p = Project(args.dir)
    ok = notify(p, args.message)
    say(args, {"sent": ok}, "sent" if ok else "No notify command in %s (see docs)" % CONFIG_NAME)


def main(argv=None):
    ap = JsonParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    s = add("serve", cmd_serve, round_=False)
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
    s = add("meta-brief", cmd_meta_brief)
    s.add_argument("--reviewer", help="only this reviewer (default: every reviewer with a saved verdict)")
    s = add("meta", cmd_meta)
    s.add_argument("--reviewer", required=True)
    s.add_argument("file", nargs="?", default=None,
                   help="the checker's reply (a file, or - for standard input; default: rounds/r<N>/meta/<reviewer>.json)")
    s = add("report", cmd_report, round_=False)
    s.add_argument("--no-notify", action="store_true")
    s = add("notify", cmd_notify, round_=False)
    s.add_argument("message", nargs="?", default="mStack: test notification")
    run_cli(ap, argv)


if __name__ == "__main__":
    main()
