"""Check, save and run command line reviewers; maker and model are recorded on every verdict."""
import json
import os
import re
import subprocess
import sys
import time

import briefs  # noqa: E402
import readiness  # noqa: E402
from eval_common import SEVERITIES, SKILL, fill


def reviewer_model(r):
    if r.get("model"):
        return r["model"]
    cmd = r.get("command")
    if not cmd:
        return None
    parts = cmd if isinstance(cmd, list) else cmd.split()
    for i, p in enumerate(parts):
        if p in ("--model", "-m") and i + 1 < len(parts):
            return parts[i + 1]
    return None


def verdict_identity(r):
    maker = r.get("maker")
    model = reviewer_model(r)
    return maker, model


def apply_verdict_identity(v, r):
    maker, model = verdict_identity(r)
    if maker is not None:
        v["maker"] = maker
    if model is not None:
        v["model"] = model
    return v


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
    apply_verdict_identity(v, r)
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
    home = os.path.expanduser("~")
    values = {"work": work, "reply": reply, "brief": brief, "dir": p.dir, "round": n, "skill": SKILL, "home": home}
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


def save_comparison(p, n, rid, v):
    os.makedirs(p.rdir(n, "verdicts"), exist_ok=True)
    path = p.rdir(n, "verdicts", rid + ".compare.json")
    v.setdefault("reviewer", rid)
    v.setdefault("round", n)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2, ensure_ascii=False)
    return path


def cmd_verdict(args):
    from eval_common import CONFIG_NAME
    from eval_loop import Project, next_step, say

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
    from eval_loop import Project, say

    p = Project(args.dir)
    probs = check_verdict(p, extract_json(read_input(args.file)))
    say(args, {"ok": not probs, "problems": probs}, "fits the reply format" if not probs else "- " + "\n- ".join(probs))
    sys.exit(1 if probs else 0)


def read_input(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()
