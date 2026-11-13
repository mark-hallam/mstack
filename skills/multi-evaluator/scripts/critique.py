"""Critique checks: a separate checker model re-tests one reviewer's findings in the live product.

After a reviewer's verdict is saved, `meta-brief` writes rounds/r<N>/briefs/<reviewer>-meta.md. A checker (by
default Claude Opus 5.5, in fresh context, never the agent that wrote the review) follows it and writes
rounds/r<N>/meta/<reviewer>.json, or replies with the JSON and `meta` saves it. The report then shows how far
each reviewer's critique held up, and the evaluator scoreboard (evalboard.py) records it across projects.
Python 3.9 or later, standard library only.
"""
import json
import os
import shlex
import sys

import briefs  # noqa: E402
from eval_common import SEVERITIES

HERE = os.path.dirname(os.path.abspath(__file__))
VERDICTS = ("confirmed", "partly", "not-reproduced", "wrong")
DEFAULT_CHECKER = {"name": "Claude Opus 5.5", "maker": "Anthropic", "model": "claude-opus-5-5"}


def checker(p):
    """Who checks the critiques: the config's "checker" (a name, or an object with name, maker and model)."""
    c = p.cfg.get("checker")
    if isinstance(c, str):
        return dict(DEFAULT_CHECKER, name=c, maker=None, model=None)
    if isinstance(c, dict) and c.get("name"):
        return dict(DEFAULT_CHECKER, **c)
    return dict(DEFAULT_CHECKER)


def meta_path(p, n, rid):
    return p.rdir(n, "meta", rid + ".json")


def meta_brief(p, n, rid):
    """The checker's brief for one reviewer: generic, with this project's names, paths and address filled in."""
    me = os.path.join(HERE, "eval_loop.py")
    target = p.cfg.get("target") or {}
    port = briefs.reviewer_port(len(p.reviewers()) + 1 + [r["id"] for r in p.reviewers()].index(rid))
    if target.get("start"):
        reach = ("Start your own copy of the product on your own port, in the background, and stop it when you finish:\n"
                 "  `python3 %s serve --dir %s --port %d`\n  It prints `ready: <address>` when it answers."
                 % (shlex.quote(me), shlex.quote(p.dir), port))
    else:
        reach = "The live product is at %s." % briefs.fill(target.get("url", ""), {"port": port})
    lines = [
        "# Critique check: is this reviewer right?", "",
        "You are a senior UX (user experience) lead checking ONE reviewer's critique of %s. You are not reviewing the "
        "product from scratch: you are judging how good this reviewer's findings are, so the team knows which "
        "reviewers to trust." % p.name, "",
        "About the product: %s" % (p.cfg.get("about") or "(see the reviewer's brief)"), "",
        "## What you get", "",
        "- The reviewer's verdict (JSON): `%s`" % p.rdir(n, "verdicts", rid + ".json"),
        "- The brief that reviewer worked from (journeys, test accounts, how to drive the product): `%s`"
        % p.rdir(n, "briefs", rid + ".md"),
        "- This round's fixed screenshots: `%s`" % p.rdir(n, "shots"),
        "- %s" % reach,
        "- The journey driver, a real headless Chrome: `node %s <steps.json> <out-folder>` (read the top of that file "
        "for the step format; keep your files in `%s`)." % (shlex.quote(briefs.DRIVER), p.rdir(n, "work", rid + "-meta")), "",
        "## Rules", "",
        "- Use only the accounts and test data named in that reviewer's brief. Mute audio in any browser you start "
        "(Chrome's --mute-audio flag).",
        "- Prefer looking over changing. Never submit real payments, messages or personal data, and do not delete or "
        "create accounts. If you change a setting, put it back.",
        "- Do not read other reviewers' verdicts, briefs or work folders, earlier rounds, or report.html, and do not "
        "edit the product's files.",
        "- Check every finding with severity blocker, high or medium; check low ones only if quick. For each, look at the "
        "real screen (or this round's screenshots) and decide whether it is true.", "",
        "## For each finding, decide", "",
        "- **verdict**: `confirmed` (true as written), `partly` (a real problem, but overstated or misdescribed), "
        "`not-reproduced` (you could not see it after a fair try) or `wrong` (the product clearly does not behave that "
        "way, or the claim misreads the screen).",
        "- **severity_ok**: true if the severity fits (a blocker stops the journey or breaks safety or trust; high badly "
        "hurts the journey; medium is a real but survivable problem; low is polish). Otherwise give `suggested_severity`.",
        "- **fix_quality**: 0 (vague or harmful), 1 (reasonable), 2 (specific, correct and the best fix).",
        "- **note**: one short sentence of evidence (what you saw, where).", "",
        "## Then judge the reviewer as a whole", "",
        "- **accuracy**: share of checked findings that are confirmed or partly (0 to 1).",
        "- **calibration**: do the 0 to 10 journey scores fit what you saw? List any journey score that is clearly too "
        "high or too low, with your score.",
        "- **missed**: up to five important problems you saw on the journeys that this reviewer missed (severity and one "
        "line each).",
        "- **usefulness**: 0 to 10, how much a product team would gain from acting on this critique.",
        "- **critique_quality**: 0 to 10 overall, weighing accuracy, severity judgement, specificity of fixes, "
        "calibration and coverage.",
        "- **summary**: two or three plain sentences.", "",
        "## Reply format", "",
        "Write JSON only to `%s`:" % meta_path(p, n, rid), "",
        '{"reviewer": "%s", "round": %d, "checked": [{"journey": <id>, "where": "...", "claim": "short restatement", '
        '"severity": "...", "verdict": "confirmed|partly|not-reproduced|wrong", "severity_ok": true, '
        '"suggested_severity": null, "fix_quality": 0, "note": "..."}],' % (rid, n),
        ' "accuracy": 0.0, "calibration": [{"journey": <id>, "their_score": 0, "your_score": 0, "why": "..."}], '
        '"missed": [{"journey": <id>, "severity": "...", "problem": "..."}],',
        ' "usefulness": 0, "critique_quality": 0, "summary": "..."}', "",
        "Then reply with just the critique_quality, the accuracy and a one-line summary.", ""]
    return "\n".join(lines)


def check_meta(v, rid=None):
    """Problems with a critique check, as plain sentences (an empty list means it is fine)."""
    if not isinstance(v, dict):
        return ["The critique check is not a JSON object."]
    probs = []
    num = lambda x, hi: isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= hi   # noqa: E731
    if rid and v.get("reviewer") not in (rid, None):
        probs.append("reviewer is %r, expected %r." % (v.get("reviewer"), rid))
    checked = v.get("checked")
    if not isinstance(checked, list):
        probs.append("checked must be a list of the findings you re-tested.")
        checked = []
    for i, c in enumerate(checked, 1):
        if not isinstance(c, dict):
            probs.append("checked %d must be an object." % i)
            continue
        if c.get("verdict") not in VERDICTS:
            probs.append("checked %d: verdict must be one of %s." % (i, ", ".join(VERDICTS)))
        if c.get("severity") not in SEVERITIES:
            probs.append("checked %d: severity must be blocker, high, medium or low." % i)
        if not num(c.get("fix_quality"), 2):
            probs.append("checked %d: fix_quality must be 0, 1 or 2." % i)
    if not num(v.get("accuracy"), 1):
        probs.append("accuracy must be a number from 0 to 1.")
    for k in ("critique_quality", "usefulness"):
        if not num(v.get(k), 10):
            probs.append("%s must be a number from 0 to 10." % k)
    for k in ("calibration", "missed"):
        if k in v and not isinstance(v[k], list):
            probs.append("%s must be a list." % k)
    return probs


def load_meta(p, n):
    out = {}
    mdir = p.rdir(n, "meta")
    for f in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        if f.endswith(".json"):
            try:
                with open(os.path.join(mdir, f), encoding="utf-8") as fh:
                    out[f[:-5]] = json.load(fh)
            except ValueError:
                pass
    return out


def summary(m):
    """The figures the report and the scoreboard show for one critique check."""
    checked = [c for c in m.get("checked", []) if isinstance(c, dict)]
    serious = [c for c in checked if c.get("severity") in ("blocker", "high")]
    held = lambda cs: sum(c.get("verdict") in ("confirmed", "partly") for c in cs)   # noqa: E731
    return {"critique_quality": m.get("critique_quality"), "usefulness": m.get("usefulness"), "accuracy": m.get("accuracy"),
            "checked": len(checked), "held": held(checked),
            "confirmed": sum(c.get("verdict") == "confirmed" for c in checked),
            "partly": sum(c.get("verdict") == "partly" for c in checked),
            "not_reproduced": sum(c.get("verdict") == "not-reproduced" for c in checked),
            "wrong": sum(c.get("verdict") == "wrong" for c in checked),
            "serious": len(serious), "serious_held": held(serious),
            "severity_ok": round(sum(bool(c.get("severity_ok")) for c in checked) / len(checked), 2) if checked else None,
            "fix_quality": round(sum(c.get("fix_quality") or 0 for c in checked) / (2.0 * len(checked)), 2) if checked else None,
            "missed": len(m.get("missed") or []), "summary": m.get("summary", "")}


def save_meta(p, n, rid, v):
    v.setdefault("reviewer", rid)
    v.setdefault("round", n)
    v.setdefault("checker", checker(p)["name"])
    os.makedirs(p.rdir(n, "meta"), exist_ok=True)
    path = meta_path(p, n, rid)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------- commands

def cmd_meta_brief(args):
    from eval_loop import Project, say

    p = Project(args.dir)
    n = p.need_round(args.round)
    done = p.verdicts(n)
    want = [r["id"] for r in p.enabled_reviewers() if not args.reviewer or r["id"] == args.reviewer]
    if args.reviewer and args.reviewer not in [r["id"] for r in p.reviewers()]:
        raise SystemExit("No reviewer %r in mstack-eval.json" % args.reviewer)
    written, waiting = [], []
    os.makedirs(p.rdir(n, "briefs"), exist_ok=True)
    for rid in want:
        if rid not in done:
            waiting.append(rid)
            continue
        os.makedirs(p.rdir(n, "work", rid + "-meta"), exist_ok=True)
        path = p.rdir(n, "briefs", rid + "-meta.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(meta_brief(p, n, rid))
        written.append(path)
    who = checker(p)["name"]
    note = ("Give each -meta brief to %s in fresh context (never the agent that wrote that review). It writes "
            "rounds/r%d/meta/<reviewer>.json; or save its reply with: meta --reviewer <id> <reply>" % (who, n))
    data = {"round": n, "checker": who, "briefs": written, "waiting_for_verdicts": waiting, "note": note}
    say(args, data, "\n".join(written + (["no verdict yet from: " + ", ".join(waiting)] if waiting else []) + [note]))


def cmd_meta(args):
    from eval_loop import Project, say
    from verdicts import extract_json, read_input

    p = Project(args.dir)
    n = p.need_round(args.round)
    if not p.reviewer(args.reviewer):
        raise SystemExit("No reviewer %r in mstack-eval.json" % args.reviewer)
    if args.file:
        raw = read_input(args.file)
    elif os.path.exists(meta_path(p, n, args.reviewer)):     # the checker wrote the file itself: check it in place
        with open(meta_path(p, n, args.reviewer), encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = read_input("-")
    v = extract_json(raw or "")
    probs = check_meta(v, args.reviewer)
    if not probs and args.reviewer not in p.verdicts(n):
        probs.append("save %s's verdict for round %d first: the critique check re-tests that verdict." % (args.reviewer, n))
    if probs:
        say(args, {"ok": False, "problems": probs}, "Not saved:\n- " + "\n- ".join(probs))
        sys.exit(1)
    path = save_meta(p, n, args.reviewer, v)
    s = summary(v)
    data = {"ok": True, "saved": path, "critique_quality": s["critique_quality"], "accuracy": s["accuracy"],
            "held": "%d of %d" % (s["held"], s["checked"])}
    data["scoreboard"] = auto_record(p, n)
    say(args, data)


def auto_record(p, n):
    """Record the round on the private evaluator scoreboard. Never fails the command it runs inside."""
    try:
        import evalboard
        return evalboard.record_project(p, n)
    except (Exception, SystemExit) as e:  # the scoreboard is a side record; a problem there never blocks the loop
        return "not recorded: %s" % e
