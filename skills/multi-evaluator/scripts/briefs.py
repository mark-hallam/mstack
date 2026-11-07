"""The briefs each reviewer gets, written so the scoring pass is blind. Used by eval_loop.py brief.

Two briefs per reviewer per round:

- the scoring brief (`<reviewer>.md`): the product, the set up, the journeys, the criteria, and this
  round's fixed screenshots only. No earlier screenshots, no earlier scores, no design direction and no
  expected answer, because a judge that sees them anchors on them. Constraints the fixes must respect
  (the config's `rules`) are listed apart, marked "not scored". This is the score of record.
- the comparison brief (`<reviewer>-compare.md`, from round 2): given to the same reviewer only after its
  verdict is saved. It shows last round's screenshots beside this round's and what changed, and asks what
  improved, what regressed and what is unchanged. It carries no scores and never replaces the verdict.

A web chat reviewer (kind "chat") gets a paste-ready scoring brief: a public address if the product has
one, otherwise the fixed screenshots and their visible text to upload, and the brief says which.
"""
import json
import os
import re
import shlex
import sys

import regrade

_MSTACK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "mstack", "scripts")
if _MSTACK not in sys.path:
    sys.path.insert(0, _MSTACK)
import rules as rules_file  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "drive.mjs")
CONTROL = "control"

REPLY_FORMAT = """{"reviewer": "%(rid)s", "round": %(n)d,
 "journeys": [{"id": <journey id>, "name": "...", "score": <0 to 10>,
   "if_fixed": <0 to 10: the score if your fixes for this journey were made; never below score>,
   "what_worked": ["..."],
   "fixes": [{"severity": "blocker|high|medium|low", "where": "screen or element", "problem": "...", "fix": "..."}]}],
 "overall": <0 to 10>,
 "top_fixes": ["the five changes that would raise the scores most"],
 "broken": ["anything that errored, did nothing, or showed wrong data"],
 "could_not_test": ["optional: what you could not reach or try, and why"],
 "did_not_touch": ["optional: anything you deliberately avoided, for example payments"]}

A **blocker** is a problem that stops the person finishing the journey, or breaks a safety or trust rule. A journey
with a blocker cannot score above 5. High, medium and low are for problems that do not stop the journey."""

COMPARE_FORMAT = """{"reviewer": "%(rid)s", "round": %(n)d,
 "compare": {"improved": ["what is better than last round, one line each"],
             "regressed": ["what got worse or broke"],
             "unchanged": ["what is still in the way"],
             "note": "one sentence"},
 "regrade": [{"id": "f1", "state": "done|partly|not|regressed|not_testable",
              "seen": "the exact words or state on screen that prove it"}]}"""


def fill(value, values):
    if isinstance(value, str):
        for k, v in values.items():
            value = value.replace("{%s}" % k, str(v))
    return value


def check_personas(p):
    """Refuse a journey that names a persona the config does not define."""
    known = set(x.get("id") for x in p.cfg.get("personas") or [] if isinstance(x, dict))
    bad = ["journey %s names persona %r" % (j["id"], j["persona"]) for j in p.journeys() if j.get("persona") and j["persona"] not in known]
    if bad:
        raise SystemExit("Unknown persona: %s. Define it under \"personas\" in mstack-eval.json (known: %s)." % (
            "; ".join(bad), ", ".join(sorted(known)) or "none"))


def journey_persona(p, j):
    who = next((x.get("who") for x in p.cfg.get("personas") or [] if isinstance(x, dict) and x.get("id") == j.get("persona")), None)
    return " Play this person: %s" % who if who else ""


def public_url(p):
    """The product's address if it is reachable from outside this computer (so a web chat can open it)."""
    url = (p.cfg.get("target") or {}).get("url", "")
    if not url or "{port}" in url or re.search(r"://(127\.|localhost|0\.0\.0\.0|\[::1\]|10\.|192\.168\.)", url):
        return None
    return url


def head(p, n, rid):
    return ["# %s: independent design review, round %d" % (p.name, n), "",
            "You are an independent, demanding reviewer. You have never seen this product. Judge it as this person: "
            "%s Be specific and sceptical: a 10 means you could not find anything to improve for that journey, so a "
            "10 never comes with fixes. Do not be polite; be useful." % p.cfg.get("persona", "a first-time user who is not technical."),
            "", "## What it is", "", p.cfg.get("about", "(No description given.)"), ""]


def port_in_use(port):
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def reviewer_port(index):
    """A port for this reviewer's own copy of the product: 8900, 8910, 8920 and so on, skipping any port
    something on this computer already holds (another review's app, a leftover server), so two reviews
    on one computer never hand out the same port."""
    port = 8900 + 10 * index
    while port_in_use(port):
        port += 100
    return port


def setup_lines(p, n, rid, index, cdp_port):
    port = reviewer_port(index)
    target = p.cfg.get("target", {})
    me = os.path.join(HERE, "eval_loop.py")
    lines = ["## Set up", ""]
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
              "4. Work alone. Do not read other reviewers' briefs, work folders or verdicts, earlier rounds, earlier "
              "verdicts, or report.html: your scores must be your own, and this round's only.", ""]
    return lines


def chat_setup_lines(p, n, rid):
    url = public_url(p)
    lines = ["## What you can see", ""]
    if url:
        lines += ["The product is public at %s. Open it and use it as a visitor would; never submit real payments, "
                  "messages or personal data. Screenshots of its main screens are attached as well." % url, ""]
    else:
        lines += ["You cannot open the product yourself: it runs on the reviewer's own computer. You are given its "
                  "fixed screens as attached images, with the visible text of each, from %s. Score only what you can "
                  "see; where a journey needs an action you cannot take, say so in `broken` and score what the screens "
                  "show." % p.rdir(n, "shots"), ""]
    lines += ["Attached: %s" % (", ".join("%s.png" % s for s in p.shots(n)) or "(none captured yet)"), ""]
    return lines


def brand_rules(p):
    """The rules in the locked brand file the config names under "brand" (made by the design-direction skill)."""
    path = p.cfg.get("brand")
    if not path:
        return []
    try:
        with open(path if os.path.isabs(path) else os.path.join(p.dir, path), encoding="utf-8") as fh:
            return [str(r) for r in json.load(fh).get("rules", [])]
    except (OSError, ValueError, AttributeError):
        return []


def project_rule_lines(p):
    """The merged rules of the project this eval folder belongs to (config "project", else the parent folder)."""
    folder = p.cfg.get("project") or os.path.dirname(p.dir)
    merged = rules_file.merged(folder)
    return [r for items in merged["rules"].values() for r in items]


def journey_lines(p, n):
    lines = ["## The journeys for this round (score each 0 to 10)", ""]
    for j in p.journeys():
        vp = j.get("viewport")
        lines.append("%s. **%s%s.** %s%s" % (j["id"], j["name"], " (%s)" % vp if vp else "", j.get("task", ""), journey_persona(p, j)))
    control = p.cfg.get("control")
    if control and os.path.isdir(os.path.join(p.dir, CONTROL)):
        lines += ["", "Also score one **control**, id `%s`, exactly like a journey: the screens in %s (fixed screenshots "
                  "with their visible text; look at them, do not drive them). Task: %s" % (
                      CONTROL, os.path.join(p.dir, CONTROL), control.get("task", "Judge what these screens show."))]
    lines += ["", "## Score each journey on", "", "A journey only scores 10 when it meets every one of these.", ""]
    for c in p.criteria(n):
        lines.append("- **%s**: %s" % (c["name"], c.get("means", "")))
    rules = list(p.cfg.get("rules") or []) + brand_rules(p) + project_rule_lines(p)
    if rules:
        lines += ["", "## Rules your fixes must respect (not scored)", "",
                  "Do not score against these; they bound what a fix may change."]
        lines += ["- %s" % r for r in rules]
    return lines


def scoring_brief(p, n, rid, index, cdp_port=None):
    r = p.reviewer(rid) or {"id": rid}
    lines = head(p, n, rid)
    if r.get("kind") == "chat":
        lines += chat_setup_lines(p, n, rid)
    else:
        lines += setup_lines(p, n, rid, index, cdp_port)
    lines += journey_lines(p, n)
    lines += ["", "## This round's fixed screens", "",
              "This round's fixed screenshots are in %s. You are not shown earlier rounds: score what is in front of you." % p.rdir(n, "shots"),
              "", "## Reply format", "", "Return JSON only, with every journey scored:", "", REPLY_FORMAT % {"rid": rid, "n": n}, ""]
    return "\n".join(lines)


def compare_brief(p, n, rid, prev):
    changes = ""
    path = p.rdir(n, "changes.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            changes = fh.read().strip()
    lines = ["# %s: comparison pass, round %d against round %d" % (p.name, n, prev), "",
             "This is a separate, labelled comparison. It is not the score of record and carries no scores: your verdict "
             "for round %d is already saved and does not change." % n, "",
             "Last round's fixed screenshots of the same screens are in %s; this round's are in %s. The maker says this "
             "changed going into round %d:" % (p.rdir(prev, "shots"), p.rdir(n, "shots"), n), "",
             changes or "(nothing written)", ""] + regrade.brief_lines(regrade.write_list(p, n, rid, prev)) + [
             "Compare screen by screen. Say what improved, what got worse or broke, and what is still in the way. Be "
             "concrete: name the screen and the element.", "",
             "## Reply format", "", "Return JSON only:", "", COMPARE_FORMAT % {"rid": rid, "n": n}, ""]
    return "\n".join(lines)
